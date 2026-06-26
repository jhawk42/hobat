# Merge Thread Device Information, Identity values, Troubleshooting

The dashboard and Python merge pipeline support canonical identity matching across these fields:

- `rloc16`
- `extAddress`,`extaddr`,  and `Extended MAC` as one canonical `extaddr` identity
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

# Python Backend Merge System (merge_dataset.py)

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
- Handles parent object name: CLI uses `route`, REST API uses `route`

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

**Matter mDNS OMR dedup:**
- Default mode: `strict-omr`
- `_matter._tcp.local.` records that share the same `omr_ipv6_addr` are collapsed into a single merged output row
- Distinct Matter identities are preserved in `_mdns_aliases` instead of producing separate top-level rows
- Alias preservation includes `matter_fabric_node_aliases`, `fabric_id_compressed_aliases`, `node_id_aliases`, `name_aliases`, `server_aliases`, and `server_key_aliases`
- The active top-level Matter fields still follow normal mDNS precedence rules: newer `captured_at_epoch` wins, then event priority (`add` > `update` > `remove`)

**Fallback Matter identity mode:**
- Use `--matter-identity-mode composite-guard` to prevent OMR-only collapse when Matter `FabricID_compressed` + `NodeID` identities differ
- In `composite-guard` mode, records with the same OMR but different Matter composite identities remain separate merged rows

### 6. Source Precedence Rules

When conflicts occur, source precedence determines the winner:

| Source | Priority | Description |
|--------|----------|-------------|
| CLI networkdiag (fetch-all) | 100 | Most detailed CLI diagnostic data |
| CLI networkdiag (multicast-network) | 99 | Network-wide diagnostics |
| CLI meshdiag topology | 98 | Mesh topology summary |
| CLI meshdiag router neighbor tables | 97 | Router neighbor tables |
| CLI meshdiag router child tables | 96 | Router child table data |
| CLI router table | 95 | Router table snapshot |
| REST API diagnostics fetch-all | 90 | Most authoritative REST diagnostics |
| REST API mesh diagnostics fetch-all | 89 | Mesh diagnostics from REST API |
| REST API diagnostics list | 88 | Diagnostic list summary |
| REST API diagnostics | 87 | Diagnostic details |
| REST API devices fetch | 86 | Device list fetch details |
| REST API devices list | 85 | Device list summary |
| REST API devices | 84 | Device details |
| Eve topology | 60 | Legacy topology format |
| mDNS Border Router | 49 | Service discovery (BR) |
| mDNS HAP | 48 | Service discovery (HAP) |

### 7. Conflict Tracking and Provenance

All merged records include metadata:

**Source Tracking:**
```json
{
  "_source_files": [
    "td-otbr-cli-networkdiag-fetch-all.json",
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

**Matter alias preservation:**
- When `strict-omr` collapses multiple Matter operational mDNS rows into one record, the per-fabric/per-node distinctions are retained under `_mdns_aliases`
- This keeps one output row per unique OMR while preserving the distinct Matter operational identities that were observed

**Edge Cases Handled:**
- Null vs empty array distinction preserved
- Missing identity fields (records without extaddr)
- Malformed nested structures (incomplete data)
- RLOC16 reuse across different devices (uses extaddr to disambiguate)
- Partition fragmentation (multi-partition networks)
- Sequence number wraparound boundaries (254→255→0→1)

## Input Files Processed

**Default Input Files (18 total):**

CLI sources (6):
- `td-otbr-cli-router-table.json`
- `td-otbr-cli-meshdiag-topology.json`
- `td-otbr-cli-networkdiag-fetch-all.json`
- `td-otbr-cli-networkdiag-multicast-network.json`
- `td-otbr-cli-meshdiag-router-neighbortables.json`
- `td-otbr-cli-meshdiag-router-childtables.json`

REST API sources (7):
- `td-otbr-restapi-diagnostics-fetch-all.json`
- `td-otbr-restapi-mesh-diagnostics-fetch-all.json`
- `td-otbr-restapi-diagnostics-list.json`
- `td-otbr-restapi-devices-fetch.json`
- `td-otbr-restapi-devices-list.json`
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

# Basic merge with explicit strict OMR Matter collapse (same as default)
python3 -m td_cli merge-dataset --matter-identity-mode strict-omr

# Fallback mode: keep same-OMR Matter rows separate when FabricID_compressed + NodeID differ
python3 -m td_cli merge-dataset --matter-identity-mode composite-guard

# Direct invocation with options
python3 src/merge_dataset.py \
  --base-dir data/ \
   --output td-merged-topology-all.json \
   --matter-identity-mode strict-omr \
  --report-file td-merge-report.json

# Custom file selection
python3 src/merge_dataset.py \
  --base-dir data/ \
  --include-files custom-source.json \
  --exclude-files td-eve-topology.json
```

## ataset Merge Troubleshooting Guide

This guide helps diagnose and resolve common issues with the Thread topology dataset merge system.

## Table of Contents

1. [Missing Input Files](#missing-input-files)
2. [Partition Conflicts](#partition-conflicts)
3. [Route Duplicates](#route-duplicates)
4. [Data Loss Detection](#data-loss-detection)
5. [Field Name Mismatches](#field-name-mismatches)
6. [Performance Issues](#performance-issues)
7. [Conflict Investigation](#conflict-investigation)
8. [Source Precedence Issues](#source-precedence-issues)

---

## Missing Input Files

**Symptom:** Merge completes but output is sparse or missing expected devices.

**Diagnosis:**
```bash
# Check which input files exist
ls -lh data/td-*.json

# Run merge with verbose output
python3 -m td_cli merge-dataset --base-dir data/ 2>&1 | grep -i "processing\|file"
```

**Common Causes:**
- Input files not yet captured from Thread network
- Files in wrong directory
- Incorrect file naming (must match DEFAULT_INPUT_FILES patterns)

**Solutions:**

1. **Capture missing data sources:**
   ```bash
   # Capture CLI data
   python3 -m td_cli otbr-cli meshdiag topology
   python3 -m td_cli otbr-cli networkdiag poll
   
   # Capture REST API data
   python3 -m td_cli otbr-restapi devices
   python3 -m td_cli otbr-restapi diagnostics
   
   # Capture mDNS data
   python3 -m td_cli mdns thread
   ```

2. **Verify file paths:**
   ```bash
   # Check data directory
   python3 -c "from merge_dataset import DEFAULT_INPUT_FILES; print('\n'.join(DEFAULT_INPUT_FILES))"
   ```

3. **Use custom file selection:**
   ```bash
   # Exclude missing files
   python3 src/merge_dataset.py \
     --base-dir data/ \
     --exclude-files td-eve-topology.json
   
   # Include additional files
   python3 src/merge_dataset.py \
     --base-dir data/ \
     --include-files custom-snapshot.json
   ```

---

## Partition Conflicts

**Symptom:** Merge report shows partition-related conflicts or unexpected routing data.

**Diagnosis:**
```bash
# Check merge report for partition info
jq '.multi_source_nodes[] | select(._merge_conflicts != null) | {extaddr, conflicts: ._merge_conflicts}' \
  data/td-merge-report.json

# Check partition IDs in merged output
jq '[.[] | select(.leader_data != null) | {extaddr, partition: .leader_data.partition_id}] | unique_by(.partition)' \
  data/td-merged-topology-all.json
```

**Common Causes:**
- Thread network experienced partition event during data capture
- Multiple captures from different time periods
- Network instability causing temporary partitions

**Solutions:**

1. **Verify single partition:**
   ```bash
   # Check current partition
   docker exec otbr ot-ctl leaderdata
   
   # Verify partition ID is consistent
   jq '[.[] | .leader_data.partition_id] | unique' data/td-merged-topology-all.json
   ```

2. **Re-capture data during stable period:**
   - Wait for network to stabilize after partition events
   - Capture all data sources within a short time window (< 5 minutes)
   - Verify partition stability before and after capture

3. **Understand partition-scoped data:**
   - RLOC16 is only valid within a partition
   - Router IDs (0-63) are partition-local
   - Routes are only valid within the same partition_id
   - extaddr remains globally unique across partitions

---

## Route Duplicates

**Symptom:** Same route appears multiple times in merged output, or routes seem duplicated.

**Diagnosis:**
```bash
# Check for duplicate routes
jq '.[] | select(.route_data != null or .route != null) | 
   {extaddr, routes: (.route.route_data // .route.route // [])} | 
   .routes | group_by(.route_id) | map(select(length > 1))' \
  data/td-merged-topology-all.json

# Check sequence numbers
jq '.[] | select(.route_data != null) | {extaddr, seq: .route_data.id_sequence}' \
  data/td-merged-topology-all.json
```

**Common Causes:**
- Missing `id_sequence` field in source data
- Incorrect sequence number handling
- Multiple sources with different sequence numbers

**Solutions:**

1. **Verify sequence numbers present:**
   ```bash
   # Check CLI source
   jq '.[] | select(.route != null) | .route.id_sequence' \
     data/td-otbr-cli-networkdiag-fetch-all.json | head -5
   
   # Check REST API source
   jq '.[] | select(.route != null) | .route.idSequence' \
     data/td-otbr-restapi-diagnostics.json | head -5
   ```

2. **Understand merge behavior:**
   - Routes matched by `(owner_rloc16, route_id)` composite identity
   - Highest `id_sequence` wins (0-255 with wraparound)
   - Example: sequence 5 is newer than sequence 250 (wraparound)

3. **Check partition consistency:**
   ```bash
   # Routes should have same partition_id
   jq '.[] | select(.route_data != null) | 
      {rloc16, partition: (.leader_data.partition_id // "none")}' \
     data/td-merged-topology-all.json | head -10
   ```

---

## Data Loss Detection

**Symptom:** Merged output has fewer devices than expected.

**Diagnosis:**
```bash
# Count unique extaddrs in each source
for file in data/td-*.json; do
  echo "=== $file ==="
  jq '[.[] | .extaddr // .extAddress // empty] | unique | length' "$file"
done

# Count extaddrs in merged output
jq '[.[] | .extaddr // .extAddress // empty] | unique | length' \
  data/td-merged-topology-all.json

# Check merge report
jq '{total: .multi_source_nodes_total + .single_source_nodes_total, 
     multi: .multi_source_nodes_total, 
     single: .single_source_nodes_total, 
     collisions: .identity_collision_count}' \
  data/td-merge-report.json
```

**Common Causes:**
- Records without extaddr are not merged by identity
- mDNS records may not have extaddr
- Some sources provide aggregate data without per-device extaddr

**Solutions:**

1. **Verify extaddr presence:**
   ```bash
   # Find records without extaddr
   jq '.[] | select(.extaddr == null and .extAddress == null) | 
      {file: "_source_files", rloc16, name}' \
     data/td-merged-topology-all.json
   ```

2. **Check identity collision log:**
   ```bash
   # Review merge report for collisions
   jq '.identity_collisions' data/td-merge-report.json
   ```

3. **Understand merge expectations:**
   - Merge consolidates duplicate records (count decreases is expected)
   - Multi-source nodes combine information from 2+ sources
   - Single-source nodes only appear in one input file
   - mDNS records without extaddr may create separate entries

---

## Field Name Mismatches

**Symptom:** Expected fields missing or duplicated (e.g., both `extaddr` and `extAddress`).

**Diagnosis:**
```bash
# Check for mixed field naming
jq '.[] | {extaddr, extAddress, id_seq: .route.id_sequence, 
          idSeq: .route.idSequence} | select(. != {})' \
  data/td-merged-topology-all.json | head -5

# List all field names in merged output
jq '[.[] | keys[]] | unique | sort' data/td-merged-topology-all.json
```

**Common Causes:**
- Source data uses non-canonical field names
- Missing alias mapping in FIELD_ALIASES_BIDIRECTIONAL
- New data source with unknown field conventions

**Solutions:**

1. **Verify field normalization:**
   ```bash
   # Check canonical names used
   python3 -c "
   from merge_dataset import FIELD_ALIASES_BIDIRECTIONAL, get_canonical_field_name
   print(get_canonical_field_name('extAddress'))  # Should return 'extaddr'
   print(get_canonical_field_name('idSequence'))  # Should return 'id_sequence'
   "
   ```

2. **Add missing aliases:**
   
   Edit `src/merge_dataset.py` and add to `FIELD_ALIASES_BIDIRECTIONAL`:
   ```python
   FIELD_ALIASES_BIDIRECTIONAL = {
       # ... existing aliases ...
       "newFieldName": "canonical_field_name",
       "canonical_field_name": "canonical_field_name",
   }
   ```

3. **Check source conventions:**
   - CLI sources use snake_case: `id_sequence`, `route_data`, `omr_ipv6_addr`
   - REST API uses camelCase: `idSequence`, `routeData`, `omrIpv6Address`
   - All normalized to snake_case in merged output

---

## Performance Issues

**Symptom:** Merge takes too long or uses excessive memory.

**Diagnosis:**
```bash
# Measure performance with timing
time python3 src/merge_dataset.py --base-dir data/ --output test-merge.json

# Check input file sizes
du -sh data/td-*.json | sort -h

# Count total records
for file in data/td-*.json; do
  echo "$file: $(jq 'if type == "array" then length else 1 end' "$file") records"
done
```

**Performance Expectations:**
- Small networks (< 20 devices): < 0.5 seconds
- Medium networks (20-50 devices): 0.5-1.5 seconds
- Large networks (50-100 devices): 1-3 seconds
- Very large networks (> 100 devices): 3-10 seconds

**Solutions:**

1. **Optimize input files:**
   ```bash
   # Remove unnecessary fields from large files
   jq 'map(del(.verbose_diagnostic_data))' \
     data/td-otbr-cli-networkdiag-fetch-all.json > temp.json
   mv temp.json data/td-otbr-cli-networkdiag-fetch-all.json
   ```

2. **Exclude non-essential sources:**
   ```bash
   # Skip Eve topology if not needed
   python3 src/merge_dataset.py \
     --base-dir data/ \
     --exclude-files td-eve-topology.json
   ```

3. **Profile memory usage:**
   ```python
   # Run Phase 5 performance test
   python3 tests/test_phase5_e2e_validation.py 2>&1 | grep -A5 "Performance"
   ```

---

## Conflict Investigation

**Symptom:** Many conflicts logged in `_merge_conflicts` field.

**Diagnosis:**
```bash
# Count conflicts
jq '[.[] | select(._merge_conflicts != null) | ._merge_conflicts | length] | add' \
  data/td-merged-topology-all.json

# Show conflict details
jq '.[] | select(._merge_conflicts != null) | 
   {extAddress, deviceLabel, conflicts: ._merge_conflicts}' \
  data/td-merged-topology-all.json | head -20

# Group conflicts by field
jq '[.[] | select(._merge_conflicts != null) | 
    ._merge_conflicts[] | .field_path] | group_by(.) | 
    map({field: .[0], count: length})' \
  data/td-merged-topology-all.json
```

**Common Causes:**
- Different sources provide different values for the same field
- Data captured at different times (values changed)
- Field semantics differ between sources

**Solutions:**

1. **Understand conflict resolution:**
   - Non-empty existing value is preserved
   - Conflicting incoming value is logged, not applied
   - Resolution: "kept current" means base value retained

2. **Review conflict patterns:**
   ```bash
   # Find most common conflicts
   jq '[.[] | ._merge_conflicts[]? | .field_path] | 
      group_by(.) | map({field: .[0], count: length}) | 
      sort_by(.count) | reverse' \
     data/td-merged-topology-all.json
   ```

3. **Adjust source precedence if needed:**
   
   Edit `src/merge_dataset.py` to adjust `SOURCE_PRECEDENCE`:
   ```python
   SOURCE_PRECEDENCE = {
       "td-otbr-restapi-diagnostics.json": 100,  # Highest priority
       "td-otbr-cli-networkdiag-fetch-all.json": 90,
       # ... adjust as needed ...
   }
   ```

4. **Accept conflicts as normal:**
   - Conflicts indicate data reconciliation is working
   - Review specific conflicts to understand data differences
   - Most conflicts are benign (e.g., timestamp differences)

---

## Source Precedence Issues

**Symptom:** Lower-priority source data overwrites higher-priority data.

**Diagnosis:**
```bash
# Check which sources contributed to each node
jq '.[] | {extaddr, sources: ._source_files}' \
  data/td-merged-topology-all.json | head -10

# Check source precedence configuration
python3 -c "
from merge_dataset import SOURCE_PRECEDENCE
import json
print(json.dumps(SOURCE_PRECEDENCE, indent=2))
"

# Verify file processing order
python3 src/merge_dataset.py --base-dir data/ 2>&1 | grep "Processing file"
```

**Common Causes:**
- Source files processed in wrong order
- Custom source not in SOURCE_PRECEDENCE dict
- Merge logic not respecting precedence

**Solutions:**

1. **Verify precedence rules:**
   ```python
   # Check current precedence
   from merge_dataset import SOURCE_PRECEDENCE
   sorted_sources = sorted(SOURCE_PRECEDENCE.items(), 
                          key=lambda x: x[1], 
                          reverse=True)
   for source, priority in sorted_sources:
       print(f"{priority:3d}: {source}")
   ```

2. **Add custom source to precedence:**
   
   Edit `src/merge_dataset.py`:
   ```python
   SOURCE_PRECEDENCE = {
       # ... existing entries ...
       "custom-source.json": 95,  # Between REST API and CLI diagnostics
   }
   ```

3. **Understand merge order:**
   - Files sorted by precedence (highest to lowest)
   - First file becomes base
   - Subsequent files merge into base
   - Base values preserved on conflicts

---


## Output Format

The merged output (`td-merged-topology-all.json`) is a JSON array of device records with:

```json
[
  {
    "extaddr": "0011223344556677",
    "rloc16": "0x1400",
    "deviceLlabel": "Living Room HomePod",
    "route": {
      "idSequence": 15,
      "routeData": [...]
    },
    "children": [...],
    "serviceInfo": {
      "decodedProperties": {
        "vn": "Apple",
        "mn": "BorderRouter",
        "tv": "1.3.0"
      }
    },
    "_source_files": [
      "td-otbr-cli-networkdiag-fetch-all.json",
      "td-otbr-restapi-diagnostics.json",
      "td-mdns-scopes-br.json"
    ],
    "_merge_conflicts": [...]
  }
]
```

### Merge Behavior

**Identity Matching:**
- Primary identity: `extAddress` (immutable 64-bit EUI-64 address)
- Secondary: `omrIpv6Address` (stable OMR IPv6 address)
- Tertiary: `rloc16` (partition-scoped, may change)

**Route Data Merging:**
- Routes matched by `(owner_rloc16, route_id)` - no duplicates
- Highest `id_sequence` wins (with 8-bit wraparound: 5 > 250)
- Partition-aware: routes only valid within same `partition_id`

**Children Array Merging:**
- Children matched by `(parent_rloc16, child_extaddr)`
- `childId` is parent-local only (not globally unique)
- Prevents duplicate children with same extaddr

**mDNS Data Merging:**
- Timestamp precedence: newer `captured_at_epoch` wins
- Event priority: add > update > remove
- Service info deeply merged with nested structure preservation

**Field Conflicts:**
- Non-empty incoming values overwrite empty base values
- For conflicts between non-empty values: base wins, conflict logged
- Special handling for routes, children, and mDNS data

### Troubleshooting

See [doc/merge_thread_device_info.md](doc/merge_thread_device_info.md) for detailed troubleshooting guidance.

**Common Issues:**

1. **Missing input files:** Ensure all required JSON files exist in the data directory
2. **Partition conflicts:** Review `_merge_conflicts` field for partition-related issues
3. **Route duplicates:** Check that `id_sequence` is being set correctly in source data
4. **Performance:** Large networks (100+ nodes) may take 1-2 seconds; this is normal


## Getting Help

If issues persist after following this guide:

1. **Check test suites:**
   ```bash
   # Run all validation tests
   python3 tests/test_phase2_enhanced_merge.py
   python3 tests/test_phase3_mdns_merge.py
   python3 tests/test_phase4_integration.py
   python3 tests/test_phase5_e2e_validation.py
   ```

2. **Review implementation docs:**
   - `plan/phase2_implementation_summary.md` - Core merge features
   - `plan/phase3_implementation_summary.md` - mDNS integration
   - `plan/phase4_implementation_summary.md` - Integration tests
   - `doc/codebase_merging_thread_identity_values.md` - Identity matching

3. **Generate detailed merge report:**
   ```bash
   python3 src/merge_dataset.py \
     --base-dir data/ \
     --report-file detailed-report.json
   
   # Review report contents
   jq '.' data/detailed-report.json
   ```

4. **Enable debug logging:**
   
   Edit `src/merge_dataset.py` and add at top of main():
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

---

## Common Patterns and Best Practices

**Data Capture:**
- Capture all sources within 5-minute window
- Verify network is stable (no partition events)
- Check partition ID before and after capture

**Merge Validation:**
- Always generate merge report (`--report-file`)
- Review conflict count and patterns
- Verify expected device count in output

**Performance Optimization:**
- Exclude unnecessary sources with `--exclude-files`
- Remove verbose fields from large input files
- Process smaller subsets for development/testing

**Conflict Resolution:**
- Understand conflicts are normal and expected
- Use source precedence to favor authoritative sources
- Review specific conflicts only when unexpected behavior occurs

**Testing Changes:**
- Run test suites after modifications
- Test with real data before production use
- Validate backward compatibility with existing merged files
