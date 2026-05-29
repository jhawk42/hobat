# Dataset Merge Troubleshooting Guide

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
python3 src/merge_dataset.py --base-dir data/ 2>&1 | grep -i "processing\|file"
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
   {extaddr, routes: (.route_data.route_data // .route.route // [])} | 
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
   jq '.[] | select(.route_data != null) | .route_data.id_sequence' \
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
jq '.[] | {extaddr, extAddress, id_seq: .route_data.id_sequence, 
          idSeq: .route_data.idSequence} | select(. != {})' \
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
   {extaddr, device_label, conflicts: ._merge_conflicts}' \
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
- Run Phase 2-5 test suites after modifications
- Test with real data (Phase 5) before production use
- Validate backward compatibility with existing merged files
