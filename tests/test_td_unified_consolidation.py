"""Parity gates for replacing focused composites with Unified selections."""

import json
import subprocess

import pytest

from merge_dataset import DEFAULT_FULL_INPUT_FILES, build_merged_records
from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from td_health_policy import load_health_policy
from td_health_processor import build_processing_result
from td_unified_dataset import build_unified_dataset
from test_td_unified_composition import _seed_all
from test_td_unified_dataset import ROOT, SOURCE_TIME, _entry, _save, _seed


@pytest.mark.parametrize(
    ("legacy", "replacement"),
    [
        ("otbr_cli_topology", "otbr_cli_unified"),
        ("otbr_restapi_topology", "otbr_restapi_unified"),
        ("multi_source_otbr_topology_mdns", "multi_source_unified"),
    ],
)
def test_unified_preserves_original_composite_measured_health_samples(tmp_path, legacy, replacement):
    if replacement == "multi_source_unified":
        _seed_all(tmp_path)
        _save(tmp_path, EXTADDR_DEVICE_LABEL_MAP_FILENAME, {})
        entries = [_entry("otbr_cli_unified"), _entry("otbr_restapi_unified")]
    else:
        entries = [_seed(tmp_path, replacement)]
    record = {
        "extAddress": "0011223344556677",
        "rloc16": "0x1000",
        "role": "router",
        "sourceObservedAt": SOURCE_TIME,
        "macCounters": {"ifTotalPkts": 1000, "ifTotalErrorsTotalPktsRatio": 0.125},
        "mleCounters": {"newParentCount": 2, "partIdChangesCount": 0},
        "routerNeighbors": [
            {"extAddress": "8899aabbccddeeff", "rloc16": "0x2000",
             "linkQualityIn": 0, "linkQualityOut": 3, "averageRssi": -75}
        ],
    }
    for entry in entries:
        for item in entry["unified"]["inputs"]:
            if item["role"] == "records" and item["required"]:
                _save(tmp_path, item["file"], [record])
    build_unified_dataset(tmp_path, replacement)
    policy = load_health_policy()
    before = build_processing_result(data_dir=tmp_path, dataset_id=legacy, policy=policy)
    after = build_processing_result(data_dir=tmp_path, dataset_id=replacement, policy=policy)

    def metric_values(observation):
        return {
            (metric.device_id, metric.metric, metric.value, metric.unit, metric.denominator)
            for metric in observation.metrics
        }

    def relationship_values(observation):
        return {
            (link.from_device_id, link.to_device_id, link.relationship_type,
             link.link_quality_in, link.link_quality_out, link.average_rssi)
            for link in observation.relationships
        }

    assert metric_values(before.observation)
    assert relationship_values(before.observation)
    assert metric_values(before.observation) <= metric_values(after.observation)
    assert relationship_values(before.observation) <= relationship_values(after.observation)
    assert {device.device_id for device in before.observation.devices} <= {
        device.device_id for device in after.observation.devices
    }
    assert after.observation.observed_at == SOURCE_TIME
    assert all("unified" not in metric.source_file for metric in after.observation.metrics)
    assert all("unified" not in name
               for link in after.observation.relationships for name in link.source_files)


@pytest.mark.parametrize(
    ("legacy", "replacement"),
    [
        ("otbr_restapi_topology", "otbr_restapi_unified"),
        ("multi_source_merged", "multi_source_unified"),
    ],
)
def test_production_built_replacement_preserves_legacy_fields_and_graph(
    tmp_path, legacy, replacement,
):
    if replacement == "multi_source_unified":
        entry = _seed_all(tmp_path)
    else:
        entry = _seed(tmp_path, replacement)
    records = [{
        "extAddress": "0011223344556677", "rloc16": "0x1000", "role": "router",
        "sourceObservedAt": SOURCE_TIME,
        "macCounters": {"ifTotalPkts": 1000, "ifTotalErrorsTotalPktsRatio": 0},
        "mleCounters": {"newParentCount": 2, "partIdChangesCount": 0},
        "routerNeighbors": [{
            "extAddress": "8899aabbccddeeff", "rloc16": "0x2000",
            "linkQualityIn": 0, "linkQualityOut": 3, "averageRssi": -75,
        }],
    }, {
        "extAddress": "8899aabbccddeeff", "rloc16": "0x2000", "role": "router",
        "sourceObservedAt": SOURCE_TIME, "isBorderRouter": False,
    }]
    for item in _entry("otbr_restapi_unified")["unified"]["inputs"]:
        if item["role"] == "records" and item["required"]:
            _save(tmp_path, item["file"], records)
    if replacement == "multi_source_unified":
        inputs = [name for name in DEFAULT_FULL_INPUT_FILES if (tmp_path / name).exists()]
        assert all(any(name.startswith(prefix) for name in inputs) for prefix in (
            "td-otbr-cli-", "td-otbr-restapi-", "td-ha-matter-ws-", "td-mdns-",
        ))
        merged, _ = build_merged_records(tmp_path, "", inputs, {})
        assert merged
        _save(tmp_path, _entry(legacy)["files"][0], merged)
    build_unified_dataset(tmp_path, replacement)
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    router = next(row for row in rows if row.get("extAddress") == records[0]["extAddress"])
    for field in ("macCounters", "mleCounters", "routerNeighbors"):
        assert router[field] == records[0][field]
    assert router["sourceObservedAt"] == SOURCE_TIME
    other = next(row for row in rows if row.get("extAddress") == records[1]["extAddress"])
    assert other["isBorderRouter"] is False
    if replacement == "multi_source_unified":
        assert router["powerSources"] == [{"endpointId": 0, "batteryPercent": 0}]
        assert router["endpoints"] == [{"endpointId": 0, "bridged": False}]
        assert any(row.get("matter", {}).get("matterId", "").endswith("-0000000000000002")
                   for row in rows)
        assert any("ap" in row.get("nativeNodeIds", []) for row in rows)
        assert any(row.get("name") == "border-router" for row in rows)
    script = """
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {runAdaptor} from './src/js/tdash-adaptors.js';
import {buildDatasetRows} from './src/js/tdash-dataset.js';
const [directory, entries] = JSON.parse(process.argv[1]);
const models = entries.map(entry => {
  const rawFiles = entry.files.map(name => {
    const path = `${directory}/${name}`;
    return fs.existsSync(path) ? JSON.parse(fs.readFileSync(path, 'utf8')) : null;
  });
  const {rows} = buildDatasetRows(entry, rawFiles);
  return runAdaptor({entry, rawFiles, rows});
});
const edges = model => {
  const pairs = new Map();
  for (const edge of model.edgeData) {
    const endpoints = [edge.from, edge.to].map(id =>
      model.rawByIdForDetails.get(id)?.extAddress || model.nodeMap.get(id)?.extAddress);
    if (endpoints.some(value => !value)) continue;
    const key = endpoints.sort().join('|');
    const categories = pairs.get(key) ?? new Set();
    edge.linkCategories.forEach(category => categories.add(category));
    pairs.set(key, categories);
  }
  return pairs;
};
const before = edges(models[0]), after = edges(models[1]);
assert.ok(before.size > 0);
for (const [pair, categories] of before) {
  assert.ok(after.has(pair), `Missing legacy relationship: ${pair}`);
  for (const category of categories) {
    assert.ok(after.get(pair).has(category), `Missing ${category}: ${pair}`);
  }
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script,
         json.dumps([str(tmp_path), [_entry(legacy), entry]])],
        capture_output=True, text=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_selector_rollout_keeps_explicit_recipes_and_fast_same_source_workflows():
    from td_dataset_catalog import load_dataset_catalog, resolve_dataset

    catalog = load_dataset_catalog()
    assert len(catalog["datasets"]) == 43
    by_id = {entry["value"]: entry for entry in catalog["datasets"]}
    assert {
        source["value"]: source["primary_dataset_value"]
        for source in catalog["datasources"] if "primary_dataset_value" in source
    } == {
        "otbr-cli": "otbr_cli_unified",
        "otbr-restapi": "otbr_restapi_unified",
        "ha-matter-ws": "ha_matter_ws_unified",
        "multi-source": "multi_source_unified",
        "mdns": "mdns_unified",
    }
    assert {
        source["value"]: source["default_dataset_value"]
        for source in catalog["datasources"] if "default_dataset_value" in source
    } == {
        "otbr-cli": "otbr_cli_mesh_ftd",
        "otbr-restapi": "otbr_restapi_devices_diagnostics_list",
        "ha-matter-ws": "ha_matter_ws_matter_topology",
        "multi-source": "multi_source_otbr_mdns",
    }
    retired = {
        "otbr_cli_topology", "ha_matter_ws_topology_merge",
    }
    assert {value for value in retired if by_id[value].get("selectable", True) is False} == retired
    for value in retired:
        assert resolve_dataset(catalog, value) == by_id[value]
    assert sum(entry.get("selectable", True) for entry in by_id.values()) == 41
    for pending in ("otbr_restapi_topology", "multi_source_merged"):
        assert by_id[pending].get("selectable", True)
    for source in catalog["datasources"]:
        primary = source.get("primary_dataset_value")
        if primary:
            assert by_id[primary]["source"] == source["value"]
            assert by_id[primary].get("selectable", True)
        default = source.get("default_dataset_value")
        if default:
            assert by_id[default].get("selectable", True)
            assert default not in retired
    for value, source in (
        ("otbr_cli_mesh_ftd_tables_mdns", "otbr-cli"),
        ("otbr_cli_topology_mdns", "otbr-cli"),
        ("otbr_restapi_topology_mdns", "otbr-restapi"),
    ):
        entry = by_id[value]
        assert entry["source"] == source
        assert entry.get("selectable", True)
        assert all(not name.startswith("td-ha-matter") for name in entry["files"])
        other = "td-otbr-restapi" if source == "otbr-cli" else "td-otbr-cli"
        assert all(not name.startswith(other) for name in entry["files"])
    assert by_id["otbr_cli_unified"]["healthEligible"] is True
    assert by_id["otbr_restapi_unified"]["healthEligible"] is True
    assert by_id["ha_matter_ws_unified"]["healthEligible"] is True
    assert by_id["multi_source_unified"]["healthEligible"] is True
    assert by_id["mdns_unified"]["healthEligible"] is False
    assert json.dumps(catalog["mergeGroups"]["full"], sort_keys=True) == json.dumps({
        "composedOf": ["otbr-cli", "otbr-restapi", "ha-matter-ws", "mdns"],
        "excluded": {"system": "Not included in legacy full merge",
                     "eve": "Not included in legacy full merge"},
    }, sort_keys=True)
