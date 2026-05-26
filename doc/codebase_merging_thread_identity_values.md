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

---

# Python Backend Merge System (dataset_merge.py)

The Python backend provides comprehensive topology merging that processes multiple JSON files from different sources (CLI, REST API, mDNS, Eve) into a single consolidated topology file.

## Core Identity Matching

The backend merge uses the same canonical identity fields as the dashboard:

- **Primary:** `extaddr` / `extAddress` / `Extended MAC` (64-bit EUI-64 globally unique identifier)
- **Secondary:** `omr_ipv6_addr` / `omrIpv6Address` (stable Off-Mesh Routable IPv6 address)
- **Tertiary:** `rloc16` (16-bit partition-scoped routing locator)

Identity matching is case-insensitive and whitespace-trimmed. Non-empty existing values are preserved; conflicts are logged in `_merge_conflicts`.

## Advanced Merge Features

### 1. Composite Identity Matching

Beyond simple extaddr matching, the merge system handles Thread-specific composite identities:

**Route Entry Matching:**
- Composite identity: `(owner_rloc16, dest_route_id)`
- Prevents duplicate routes from the same owner to the same destination
- Handles parent object name differences: CLI uses `route_data`, REST API uses `route`

**Children Array Matching:**
- Composite identity: `(parent_rloc16, child_extaddr)`
- Critical: `childId` is parent-local only, NOT globally unique
- Prevents duplicate children with same extaddr under same parent

**Router Neighbors Matching:**
- Identity: `extaddr` or `rloc16` (fallback)
- Merges neighbor information from multiple sources

### 2. Sequence Number Precedence

Thread uses 8-bit sequence numbers (0-255) with wraparound. The merge implements RFC 1982 serial number arithmetic:

- Highest sequence number wins (with wraparound: 5 is newer than 250)
- Sequence distance calculation handles 0→255 and 255→0 boundaries
- Applied to `id_sequence` fields in route data and topology updates

### 3. Partition Awareness

Thread networks can fragment into multiple partitions:

- `partition_id` extracted from `leader_data` (32-bit value)
- RLOC16, Router ID, and routes are only valid within the same partition
- Cross-partition merging is prevented for routing data
- Missing or zero partition_id is treated as "unknown" partition

### 4. Field Name Normalization

Handles 160+ field alias mappings between different data sources:

**Convention Differences:**
- CLI sources: snake_case (e.g., `id_sequence`, `route_data`)
- REST API sources: camelCase (e.g., `idSequence`, `routeData`)
- Legacy sources: mixed conventions

**Normalization Process:**
- All fields normalized to canonical snake_case form
- Bidirectional alias mapping preserves backward compatibility
- Parent object aliases recognized (e.g., `route_data` ↔ `route`)

**Example Aliases:**
```
extAddress → extaddr
omrIpv6Address → omr_ipv6_addr
idSequence → id_sequence
childTable → children
leaderData → leader_data
```

### 5. mDNS Integration

Merges service discovery data from four mDNS scopes:

**mDNS Scopes:**
- `_meshcop._udp` - Border Router discovery
- Thread device announcements
- `_hap._tcp` - HomeKit Accessory Protocol devices
- `_matter._tcp` - Matter smart home devices

**mDNS Merge Rules:**
- Timestamp precedence: newer `captured_at_epoch` wins
- Event priority: add (3) > update (2) > remove (1)
- Service info deeply merged with nested structure preservation
- Vendor, model, and version information extracted from TXT records

### 6. Source Precedence Rules

When conflicts occur, source precedence determines the winner:

| Source | Priority | Description |
|--------|----------|-------------|
| REST API diagnostics | 100 | Most authoritative source |
| CLI networkdiag (poll) | 90 | Detailed diagnostic data |
| CLI networkdiag (multicast) | 85 | Network-wide diagnostics |
| CLI meshdiag neighbors | 80 | Router neighbor tables |
| CLI meshdiag topology | 75 | Mesh topology summary |
| CLI router table | 70 | Router table snapshot |
| mDNS Border Router | 60 | Service discovery (BR) |
| mDNS Thread | 55 | Service discovery (Thread) |
| mDNS HAP | 50 | Service discovery (HAP) |
| mDNS Matter | 45 | Service discovery (Matter) |
| Eve topology | 10 | Legacy format |

### 7. Conflict Tracking and Provenance

All merged records include metadata:

**Source Tracking:**
```json
{
  "_source_files": [
    "td-otbr-cli-networkdiag-topology-poll.json",
    "td-otbr-restapi-diagnostics.json",
    "td-mdns-scopes-br.json"
  ]
}
```

**Conflict Logging:**
```json
{
  "_merge_conflicts": [
    {
      "field_path": "mode",
      "current": "rn",
      "incoming": "r",
      "resolution": "kept current",
      "incoming_source": "td-otbr-cli-meshdiag-topology.json"
    }
  ]
}
```

## Performance Characteristics

Based on Phase 5 end-to-end validation with real data:

- **Dataset Size:** 404 input records across 12 files
- **Output:** 141 merged nodes (70 multi-source, 71 single-source)
- **Execution Time:** ~0.6 seconds
- **Memory Usage:** ~3.3 MB peak
- **Data Loss:** 0 extaddrs lost (100% preservation)

Performance scales linearly with dataset size. Networks with 100+ nodes complete in 1-2 seconds.

## Merge Behavior Details

**Empty Value Handling:**
- Empty string or `null` in incoming: preserves existing value
- Empty in existing, non-empty in incoming: updates with incoming value
- Both non-empty and different: logs conflict, keeps existing value

**Array Merging:**
- Routes: composite identity matching, no duplicates
- Children: composite identity matching, no duplicates
- Router neighbors: extaddr/rloc16 identity matching
- Other arrays: append unique elements only

**Nested Object Merging:**
- Deep merge with recursive traversal
- Special handling for Thread-specific structures (route_data, children, service_info)
- Path tracking for conflict reporting

**Edge Cases Handled:**
- Null vs empty array distinction preserved
- Missing identity fields (records without extaddr)
- Malformed nested structures (incomplete data)
- RLOC16 reuse across different devices (uses extaddr to disambiguate)
- Partition fragmentation (multi-partition networks)
- Sequence number wraparound boundaries (254→255→0→1)

## Input Files Processed

**Default Input Files (12 total):**

CLI sources (5):
- `td-otbr-cli-router-table.json`
- `td-otbr-cli-meshdiag-topology.json`
- `td-otbr-cli-networkdiag-topology-poll.json`
- `td-otbr-cli-networkdiag-topology-multicast-network.json`
- `td-otbr-cli-meshdiag-router-neighbortables.json`

REST API sources (2):
- `td-otbr-restapi-devices.json`
- `td-otbr-restapi-diagnostics.json`

mDNS sources (4):
- `td-mdns-scopes-br.json`
- `td-mdns-scopes-thread.json`
- `td-mdns-scopes-hap.json`
- `td-mdns-scopes-matter.json`

Legacy sources (1):
- `td-eve-topology.json`

## Usage

```bash
# Basic merge with defaults
python3 -m td_cli merge-dataset

# Direct invocation with options
python3 src/dataset_merge.py \
  --base-dir data/ \
  --output td-merged-topology-all.json \
  --report-file td-merge-report.json

# Custom file selection
python3 src/dataset_merge.py \
  --base-dir data/ \
  --include-files custom-source.json \
  --exclude-files td-eve-topology.json
```

## Implementation Notes

- Phases 0-5 implementation complete and validated (May 2026)
- All 54 tests passing across 5 test suites (Phases 1-5)
- Backward compatible with existing merged files
- No data loss across 69 unique extaddrs in real dataset validation
- See `plan/` directory for detailed phase documentation
