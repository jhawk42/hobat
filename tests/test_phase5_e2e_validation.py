"""
Phase 5 End-to-End Validation Tests

Tests for Phase 5 comprehensive validation:
- Run merge with real captured JSON files from data/ directory
- Validate merged output correctness
- Performance benchmarking (time and memory usage)
- Data loss detection
- Backward compatibility verification
"""

import json
import shutil
import time
import tracemalloc
import traceback
from pathlib import Path
from typing import Any
import pytest

from merge_dataset import main as merge_dataset_main


# Test data directory
DATA_DIR = Path(__file__).parent.parent / "data"
PLACEHOLDER_EXTADDRS = {"0000000000000000"}


# =============================================================================
# Test 1: End-to-End Merge with Real Data
# =============================================================================

def _data_manifest(data_dir: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(data_dir)): path.read_bytes()
        for path in sorted(data_dir.rglob("*"))
        if path.is_file()
    }


def _run_e2e_merge_with_real_data(data_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the full merge pipeline and return merged/report data."""
    output_file = data_dir / "td-merged-topology-all.json"
    args = [
        "--base-dir", str(data_dir),
        "--dataset-file", "td-otbr-cli-thread-network-info.json",
        "--output", "td-merged-topology-all.json",
        "--extaddr-map-file", "td-static-extaddr-device-label.json",
        "--report-file", "td-merge-report-phase5.json",
    ]

    exit_code = merge_dataset_main(args)
    assert exit_code == 0, f"Merge failed with exit code {exit_code}"
    assert output_file.exists(), f"Output file not created: {output_file}"
    with output_file.open("r") as file_handle:
        merged_data = json.load(file_handle)

    report_file = data_dir / "td-merge-report-phase5.json"
    assert report_file.exists(), f"Report file not created: {report_file}"
    with report_file.open("r") as file_handle:
        report_data = json.load(file_handle)

    return merged_data, report_data


@pytest.fixture(scope="module")
def isolated_data_dir(tmp_path_factory: pytest.TempPathFactory):
    original_manifest = _data_manifest(DATA_DIR)
    data_dir = tmp_path_factory.mktemp("phase5-data")
    shutil.copytree(DATA_DIR, data_dir, dirs_exist_ok=True)
    yield data_dir
    assert _data_manifest(DATA_DIR) == original_manifest


@pytest.fixture(scope="module")
def merged_bundle(isolated_data_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run merge once for module-level tests that validate merged output."""
    return _run_e2e_merge_with_real_data(isolated_data_dir)


@pytest.fixture(scope="module")
def merged_data(merged_bundle: tuple[list[dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
    return merged_bundle[0]


@pytest.fixture(scope="module")
def report_data(merged_bundle: tuple[list[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    return merged_bundle[1]


def test_e2e_merge_with_real_data(merged_data: list[dict[str, Any]], report_data: dict[str, Any]):
    """Test full merge pipeline with real captured JSON files."""
    assert isinstance(merged_data, list)
    assert len(merged_data) > 0
    assert isinstance(report_data, dict)
    assert report_data.get("total_merged_nodes") == len(merged_data)


# =============================================================================
# Test 2: Validate Merged Output Correctness
# =============================================================================

def test_validate_merged_output_correctness(merged_data: list[dict[str, Any]]):
    """Validate the correctness of merged output."""
    print("\n=== Test: Validate Merged Output Correctness ===")
    
    # Check that merged data is a list
    assert isinstance(merged_data, list), "Merged data should be a list"
    assert len(merged_data) > 0, "Merged data should not be empty"
    
    print(f"  Total merged nodes: {len(merged_data)}")
    
    # Validate each node
    nodes_with_extaddr = 0
    nodes_with_rloc16 = 0
    nodes_with_device_label = 0
    nodes_with_routes = 0
    nodes_with_children = 0
    nodes_with_mdns = 0
    nodes_with_multiple_sources = 0
    nodes_with_conflicts = 0
    
    for node in merged_data:
        assert isinstance(node, dict), "Each node should be a dict"
        
        # Count identity fields
        if "extaddr" in node or "extAddress" in node:
            nodes_with_extaddr += 1
        if "rloc16" in node:
            nodes_with_rloc16 += 1
        if "device_label" in node or "name" in node:
            nodes_with_device_label += 1
        
        # Count topology features
        if "route_data" in node or "route" in node:
            nodes_with_routes += 1
        if "children" in node or "childTable" in node:
            nodes_with_children += 1
        if "service_info" in node or "record_key" in node:
            nodes_with_mdns += 1
        
        # Count multi-source nodes
        if "_source_files" in node:
            sources = node["_source_files"]
            if isinstance(sources, list) and len(sources) > 1:
                nodes_with_multiple_sources += 1
        
        # Count nodes with conflicts
        if "_merge_conflicts" in node:
            conflicts = node["_merge_conflicts"]
            if isinstance(conflicts, list) and len(conflicts) > 0:
                nodes_with_conflicts += 1
    
    print(f"  Nodes with extaddr: {nodes_with_extaddr}")
    print(f"  Nodes with rloc16: {nodes_with_rloc16}")
    print(f"  Nodes with device_label: {nodes_with_device_label}")
    print(f"  Nodes with route data: {nodes_with_routes}")
    print(f"  Nodes with children: {nodes_with_children}")
    print(f"  Nodes with mDNS data: {nodes_with_mdns}")
    print(f"  Multi-source nodes: {nodes_with_multiple_sources}")
    print(f"  Nodes with conflicts: {nodes_with_conflicts}")
    
    # Validations
    assert nodes_with_extaddr > 0, "Should have nodes with extaddr"
    assert nodes_with_multiple_sources > 0, "Should have multi-source nodes"
    
    print("  ✅ PASS: Merged output structure is valid")


# =============================================================================
# Test 3: Performance Benchmarking
# =============================================================================

@pytest.mark.benchmark
def test_performance_benchmarking(isolated_data_dir: Path):
    """Benchmark merge performance with real data."""
    print("\n=== Test: Performance Benchmarking ===")
    
    # Start memory tracking
    tracemalloc.start()
    
    # Prepare arguments
    args = [
        "--base-dir", str(isolated_data_dir),
        "--dataset-file", "td-otbr-cli-thread-network-info.json",
        "--output", "td-merged-topology-all-perf.json",
        "--extaddr-map-file", "td-static-extaddr-device-label.json",
    ]
    
    # Run merge and measure time
    start_time = time.time()
    exit_code = merge_dataset_main(args)
    end_time = time.time()
    
    # Get memory usage
    current_memory, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Clean up temporary file
    temp_output = isolated_data_dir / "td-merged-topology-all-perf.json"
    if temp_output.exists():
        temp_output.unlink()
    
    # Calculate metrics
    execution_time = end_time - start_time
    peak_memory_mb = peak_memory / 1024 / 1024
    
    print(f"  Execution time: {execution_time:.2f}s")
    print(f"  Peak memory usage: {peak_memory_mb:.2f} MB")
    
    # Performance assertions
    assert exit_code == 0, f"Benchmark merge failed with exit code {exit_code}"
    assert execution_time < 30.0, f"Merge took too long: {execution_time:.2f}s (expected < 30s)"
    assert peak_memory_mb < 500, f"Memory usage too high: {peak_memory_mb:.2f} MB (expected < 500 MB)"
    
    print("  ✅ PASS: Performance is acceptable")
    
# =============================================================================
# Test 4: Data Loss Detection
# =============================================================================

def test_data_loss_detection(merged_data: list[dict[str, Any]], isolated_data_dir: Path):
    """Detect potential data loss during merge."""
    print("\n=== Test: Data Loss Detection ===")
    
    # Load input files and count records
    input_files = [
        "td-otbr-cli-router-table.json",
        "td-otbr-cli-meshdiag-topology.json",
        "td-otbr-cli-networkdiag-fetch-all.json",
        "td-otbr-cli-networkdiag-multicast-network.json",
        "td-otbr-cli-meshdiag-router-neighbortables.json",
        "td-otbr-restapi-devices.json",
        "td-otbr-restapi-diagnostics.json",
        "td-mdns-scopes-br.json",
        "td-mdns-scopes-thread.json",
        "td-mdns-scopes-hap.json",
        "td-mdns-scopes-matter.json",
        "td-eve-topology.json",
    ]
    
    total_input_records = 0
    input_extaddrs = set()
    
    for filename in input_files:
        filepath = isolated_data_dir / filename
        assert filepath.is_file(), f"Required Phase 5 fixture is missing: {filename}"
        
        with filepath.open("r") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    total_input_records += len(data)
                    # Extract extaddrs
                    for record in data:
                        if isinstance(record, dict):
                            extaddr = record.get("extaddr") or record.get("extAddress")
                            if extaddr:
                                normalized = str(extaddr).strip().lower()
                                if normalized and normalized not in PLACEHOLDER_EXTADDRS:
                                    input_extaddrs.add(normalized)
                elif isinstance(data, dict):
                    total_input_records += 1
                    extaddr = data.get("extaddr") or data.get("extAddress")
                    if extaddr:
                        normalized = str(extaddr).strip().lower()
                        if normalized and normalized not in PLACEHOLDER_EXTADDRS:
                            input_extaddrs.add(normalized)
            except json.JSONDecodeError as exc:
                pytest.fail(f"Required Phase 5 fixture is malformed: {filename}: {exc}")
    
    print(f"  Total input records: {total_input_records}")
    print(f"  Unique extaddrs in inputs: {len(input_extaddrs)}")
    
    merged_extaddrs = set()
    for node in merged_data:
        if isinstance(node, dict):
            extaddr = node.get("extaddr") or node.get("extAddress")
            if extaddr:
                normalized = str(extaddr).strip().lower()
                if normalized and normalized not in PLACEHOLDER_EXTADDRS:
                    merged_extaddrs.add(normalized)
    
    print(f"  Merged output nodes: {len(merged_data)}")
    print(f"  Unique extaddrs in output: {len(merged_extaddrs)}")
    
    # Check for data loss (merged should have all unique extaddrs)
    missing_extaddrs = input_extaddrs - merged_extaddrs
    if missing_extaddrs:
        print(f"  ⚠️  Missing {len(missing_extaddrs)} extaddrs in merged output:")
        for extaddr in list(missing_extaddrs)[:5]:
            print(f"     - {extaddr}")
        if len(missing_extaddrs) > 5:
            print(f"     ... and {len(missing_extaddrs) - 5} more")
    
    # Validate: merged nodes should be <= total unique extaddrs
    # (merge combines records, so count should be less than or equal)
    assert len(merged_data) <= total_input_records, \
        f"Merged count ({len(merged_data)}) should not exceed input records ({total_input_records})"
    
    # All input extaddrs should be in merged output
    assert len(missing_extaddrs) == 0, \
        f"Data loss detected: {len(missing_extaddrs)} extaddrs missing from merged output"
    
    print("  ✅ PASS: No data loss detected")


# =============================================================================
# Test 5: Backward Compatibility Verification
# =============================================================================

def test_backward_compatibility(merged_data: list[dict[str, Any]]):
    """Verify backward compatibility with existing merged files."""
    print("\n=== Test: Backward Compatibility ===")
    
    # Verify expected structure
    assert isinstance(merged_data, list), "Merged data should be a list (backward compatible)"
    
    # Check that essential fields are present in at least some nodes
    has_extaddr = any("extaddr" in node or "extAddress" in node for node in merged_data if isinstance(node, dict))
    has_rloc16 = any("rloc16" in node for node in merged_data if isinstance(node, dict))
    has_source_tracking = any("_source_files" in node for node in merged_data if isinstance(node, dict))
    
    assert has_extaddr, "Should have nodes with extaddr (essential field)"
    assert has_rloc16, "Should have nodes with rloc16 (essential field)"
    assert has_source_tracking, "Should have source tracking (_source_files)"
    
    print("  ✅ Essential fields present")
    print("  ✅ Structure is backward compatible")
    print("  ✅ PASS: Backward compatibility verified")


# =============================================================================
# Test 6: Validate Specific Merge Features
# =============================================================================

def test_validate_specific_merge_features(merged_data: list[dict[str, Any]]):
    """Validate specific Phase 2-4 merge features are working."""
    print("\n=== Test: Validate Specific Merge Features ===")
    
    # Feature 1: Route data merge (Phase 2)
    nodes_with_routes = [n for n in merged_data if "route_data" in n or "route" in n]
    if nodes_with_routes:
        sample_route_node = nodes_with_routes[0]
        route_data = sample_route_node.get("route_data") or sample_route_node.get("route")
        print(f"  ✅ Route data merge: Found {len(nodes_with_routes)} nodes with routes")
        
        # Check for sequence field
        has_sequence = "id_sequence" in route_data or "idSequence" in route_data
        if has_sequence:
            print("     - Sequence precedence field present")
    
    # Feature 2: Children array merge (Phase 2)
    nodes_with_children = [n for n in merged_data if "children" in n or "childTable" in n]
    if nodes_with_children:
        print(f"  ✅ Children array merge: Found {len(nodes_with_children)} nodes with children")
    
    # Feature 3: mDNS data merge (Phase 3)
    nodes_with_mdns = [n for n in merged_data if "service_info" in n or "record_key" in n]
    if nodes_with_mdns:
        print(f"  ✅ mDNS integration: Found {len(nodes_with_mdns)} nodes with mDNS data")
    
    # Feature 4: Multi-source merge (Phase 2-3)
    multi_source_nodes = [n for n in merged_data 
                          if "_source_files" in n and isinstance(n["_source_files"], list) and len(n["_source_files"]) > 1]
    print(f"  ✅ Multi-source merge: Found {len(multi_source_nodes)} nodes from multiple sources")
    
    # Feature 5: Conflict tracking (Phase 2)
    nodes_with_conflicts = [n for n in merged_data 
                           if "_merge_conflicts" in n and isinstance(n["_merge_conflicts"], list) and len(n["_merge_conflicts"]) > 0]
    if nodes_with_conflicts:
        print(f"  ✅ Conflict tracking: Found {len(nodes_with_conflicts)} nodes with tracked conflicts")
    
    # Feature 6: Partition awareness (Phase 2)
    nodes_with_partition = [n for n in merged_data 
                           if "leader_data" in n or "leaderData" in n]
    if nodes_with_partition:
        print(f"  ✅ Partition awareness: Found {len(nodes_with_partition)} nodes with partition data")

    assert nodes_with_routes, "Maintained snapshot must exercise route merging"
    assert nodes_with_children, "Maintained snapshot must exercise child relationships"
    assert multi_source_nodes, "Maintained snapshot must exercise multi-source merging"
    assert nodes_with_conflicts, "Maintained snapshot must exercise conflict tracking"
    assert nodes_with_partition, "Maintained snapshot must exercise partition-aware records"

    print("  ✅ PASS: All Phase 2-4 features present in merged output")


# =============================================================================
# Run All Tests
# =============================================================================

def run_all_tests():
    """Run all Phase 5 end-to-end validation tests."""
    print("=" * 70)
    print("Phase 5 End-to-End Validation Tests")
    print("=" * 70)
    
    # Test 1: Run full merge with real data
    merged_data, report_data = _run_e2e_merge_with_real_data()
    
    # Test 2: Validate merged output correctness
    test_validate_merged_output_correctness(merged_data)
    
    # Test 3: Performance benchmarking
    test_performance_benchmarking()
    
    # Test 4: Data loss detection
    test_data_loss_detection()
    
    # Test 5: Backward compatibility
    test_backward_compatibility()
    
    # Test 6: Validate specific merge features
    test_validate_specific_merge_features(merged_data)
    
    print("\n" + "=" * 70)
    print("✅ ALL PHASE 5 TESTS PASSED!")
    print("=" * 70)
    print("\nPhase 5 Validation Summary:")
    print("  ✅ End-to-end merge with real data successful")
    print("  ✅ Merged output structure validated")
    print(f"  ✅ Performance: {perf_metrics['execution_time_seconds']:.2f}s, {perf_metrics['peak_memory_mb']:.2f} MB")
    print("  ✅ No data loss detected")
    print("  ✅ Backward compatibility verified")
    print("  ✅ All Phase 2-4 features present in output")
    print("\nPhase 5 end-to-end validation is COMPLETE and VALIDATED!")
    print(f"\nTotal Tests Run: 6")
    print("Test Pass Rate: 100%")


if __name__ == "__main__":
    run_all_tests()
