from __future__ import annotations

import asyncio
import copy
import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from ha_matter_ws_contract import MatterWsContractError
from ha_matter_ws_native_topology import validate_native_topology
from ha_matter_ws_snapshots import MatterSnapshotSecurityError
from ha_matter_ws_unified import (
    normalize_border_routers, normalize_inventory, normalize_native_topology,
)
import td_unified_dataset as unified
import td_webserver
from td_dataset_catalog import load_dataset_catalog, resolve_dataset, validate_dataset_catalog
from td_network_identity import NetworkScope
from td_source_capabilities import SourceCapabilityService
from util_data import write_network_scope
from webserver_test_support import make_data_request, make_webserver_app, reset_webserver_state


DATASET_IDS = ("otbr_cli_unified", "otbr_restapi_unified", "ha_matter_ws_unified", "mdns_unified")
NETWORK = "extpan:1234567890abcdef"
OTHER_NETWORK = "extpan:abcdef1234567890"
SOURCE_TIME = "2026-01-01T00:00:00+00:00"
ROOT = Path(__file__).resolve().parents[1]


def _entry(dataset_id):
    return resolve_dataset(load_dataset_catalog(), dataset_id)


def _save(directory, filename, payload, *, scope=NETWORK):
    path = directory / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, ns=(1_767_225_600_000_000_000, 1_767_225_600_000_000_000))
    if scope is not None:
        write_network_scope(path, NetworkScope(
            scope[7:], None, "observed", None, SOURCE_TIME, (filename,),
        ))
    return path


def _seed(directory, dataset_id, *, empty=False):
    if dataset_id == "ha_matter_ws_unified":
        return _seed_ha(directory, empty=empty)
    entry = _entry(dataset_id)
    for item in entry["unified"]["inputs"]:
        if item["role"] == "identity":
            _save(directory, item["file"], {
                "extPanId": NETWORK[7:], "networkName": "test",
                "networkKey": "must-not-be-published", "pskc": "must-not-be-published",
            })
        elif item["role"] == "outcome":
            _save(directory, item["file"], {
                "deviceResults": [{"status": "completed"}], "completedAt": SOURCE_TIME,
            })
        elif item["required"]:
            record = {"extAddress": "0011223344556677", "rloc16": "0x1000",
                      "deviceLabel": "router", "sourceObservedAt": SOURCE_TIME}
            if dataset_id == "mdns_unified":
                record = {"scope": "_meshcop._udp.local.", "name": "border-router",
                          "serviceInfo": {"name": "border-router", "server": "router.local."}}
            rows = [] if empty else [record]
            _save(directory, item["file"], {"data": rows} if item["extractor"] == "json-api" else rows)
    return entry


def _artifacts(directory, entry):
    names = [*unified._artifact_names(entry), entry["unified"]["reportFile"]]
    return {name: ((directory / name).read_bytes(), (directory / name).stat().st_mtime_ns)
            for name in names}


def _mdns_omr_services():
    address = "fd6b:32e0:d18:0:131f:4a34:d524:2457"
    return [{
        "scope": "_matter._tcp.local.", "name": f"{fabric}-0000000000000001._matter._tcp.local.",
        "omrIpv6Address": address, "capturedAtEpoch": 1_767_225_600,
        "serviceInfo": {
            "server": "device.local.", "port": 5540,
            "properties": {
                "fabricIdCompressed": {"decoded": fabric},
                "nodeId": {"decoded": "0000000000000001"},
            },
        },
    } for fabric in ("1111222233334444", "9999222233334444")]


def _seed_mdns_omr_services(directory):
    entry = _seed(directory, "mdns_unified")
    services = _mdns_omr_services()
    later = copy.deepcopy(services)
    later[0]["capturedAtEpoch"] += 1
    later[0]["serviceInfo"]["port"] = 5541
    later[0]["omrIpv6Address"] = "FD6B:32E0:0D18:0000:131F:4A34:D524:2457"
    for item in entry["unified"]["inputs"]:
        records = services if item["file"] == "td-mdns-scopes-matter.json" else (
            later if item["file"] == "td-mdns-scopes-thread.json" else []
        )
        _save(directory, item["file"], records)
    return entry


def test_mdns_unified_groups_omr_without_losing_fabrics_events_or_lineage(tmp_path):
    entry = _seed_mdns_omr_services(tmp_path)
    raw_before = {item["file"]: (tmp_path / item["file"]).read_bytes()
                  for item in entry["unified"]["inputs"]}
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    assert len(rows) == 1
    [group] = rows
    assert group["type"] == "service"
    assert group["omrIpv6Address"] == _mdns_omr_services()[0]["omrIpv6Address"]
    assert group["_networkInstance"] is None
    assert "matter" not in group and "serviceInfo" not in group and "scope" not in group
    services = group["mdnsRecords"]
    assert len(services) == 2
    assert {s["name"] for s in services} == {s["name"] for s in _mdns_omr_services()}
    assert len({s["_unifiedRecordId"] for s in services}) == 2
    assert all(s["_networkInstance"] is None for s in services)
    first = next(s for s in services if s["name"].startswith("1111222233334444"))
    assert first["capturedAtEpoch"] == 1_767_225_601
    assert first["serviceInfo"]["port"] == 5541
    assert {s["serviceInfo"]["properties"]["fabricIdCompressed"]["decoded"] for s in services} == {
        "1111222233334444", "9999222233334444",
    }
    report = unified.read_generation(tmp_path, entry, verify_inputs=True)
    group_id = group["_unifiedRecordId"]
    assert set(report["recordSources"]) == set(report["fieldSources"]) == {group_id}
    sources = report["recordSources"][group_id]
    assert len(sources) == 4
    fields = report["fieldSources"][group_id]
    assert fields["mdnsRecords"] == sources
    assert len(fields["omrIpv6Address"]) == 3
    assert all(origin in sources for origin in fields["omrIpv6Address"])
    fabric_fields = [
        origins for path, origins in fields.items()
        if path.startswith("mdnsRecords[") and path.endswith("properties.fabricIdCompressed.decoded")
    ]
    assert len(fabric_fields) == 2
    assert all(len(origins) == 2 for origins in fabric_fields)
    port_fields = [
        origins for path, origins in fields.items()
        if path.startswith("mdnsRecords[") and path.endswith("serviceInfo.port")
    ]
    assert any([o["filename"] for o in origins] == ["td-mdns-scopes-thread.json"]
               for origins in port_fields)
    assert result["healthState"] == "ineligible"
    assert raw_before == {name: (tmp_path / name).read_bytes() for name in raw_before}
    before = _artifacts(tmp_path, entry)
    assert unified.build_unified_dataset(tmp_path, entry["value"])["noOp"] is True
    assert _artifacts(tmp_path, entry) == before


def test_mdns_grouping_requires_explicit_build_to_upgrade_v6(tmp_path, monkeypatch):
    entry = _seed_mdns_omr_services(tmp_path)
    with monkeypatch.context() as previous:
        previous.setattr(unified, "BUILDER_CONTRACT", "unified-assembly-v6")
        previous.setattr(unified, "_group_mdns_services", lambda rows, *_: rows)
        old = unified.build_unified_dataset(tmp_path, entry["value"])
    assert old["rowCount"] == 2
    assert unified.read_generation(tmp_path, entry)["generationId"] == old["generationId"]
    assert len(json.loads((tmp_path / entry["files"][0]).read_text())) == 2
    upgraded = unified.build_unified_dataset(tmp_path, entry["value"])
    assert upgraded["noOp"] is False
    assert upgraded["rowCount"] == 1
    assert upgraded["generationId"] != old["generationId"]
    assert unified.build_unified_dataset(tmp_path, entry["value"])["noOp"] is True


@pytest.mark.parametrize("case", [
    "different-network", "unknown-vs-known-network", "conflicting-extaddr",
    "unspecified", "multicast", "link-local", "loopback", "invalid", "missing", "different-address",
    "singleton",
])
def test_mdns_omr_grouping_preserves_unrelated_or_unsafe_services(case):
    first, second = _mdns_omr_services()
    first_scope = second_scope = None
    if case == "different-network":
        first_scope, second_scope = NETWORK[7:], OTHER_NETWORK[7:]
    elif case == "unknown-vs-known-network":
        first_scope = NETWORK[7:]
    elif case == "conflicting-extaddr":
        first["extAddress"], second["extAddress"] = "0011223344556677", "8899aabbccddeeff"
    elif case == "missing":
        first.pop("omrIpv6Address")
        second.pop("omrIpv6Address")
    elif case == "different-address":
        second["omrIpv6Address"] = "fd6b:32e0:d18::2"
    elif case != "singleton":
        first["omrIpv6Address"] = second["omrIpv6Address"] = {
            "unspecified": "::", "multicast": "ff02::1", "link-local": "fe80::1",
            "loopback": "::1", "invalid": "not-an-address",
        }[case]
    rows, record_sources, field_sources = unified._assemble([
        (first_scope, "td-mdns-scopes-matter.json", [first]),
        (second_scope, "td-mdns-scopes-thread.json", [] if case == "singleton" else [second]),
    ])
    before = copy.deepcopy((rows, record_sources, field_sources))
    grouped = unified._group_mdns_services(rows, record_sources, field_sources)
    assert (grouped, record_sources, field_sources) == before
    assert all("mdnsRecords" not in row for row in grouped)


@pytest.mark.parametrize("case", [
    "different-services", "same-extaddr", "placeholder-extaddr", "scoped", "three-services",
])
def test_mdns_omr_groups_preserve_complete_individual_advertisements(case):
    services = _mdns_omr_services()
    scope = NETWORK[7:] if case == "scoped" else None
    if case == "different-services":
        services[1]["scope"] = "_hap._udp.local."
    elif case in {"same-extaddr", "placeholder-extaddr"}:
        for service in services:
            service["extAddress"] = (
                "0011223344556677" if case == "same-extaddr" else "0000000000000000"
            )
    elif case == "three-services":
        services.append({**services[0], "name": "another-service"})
    rows, record_sources, field_sources = unified._assemble([
        (scope, "td-mdns-scopes-thread.json", services),
    ])
    before = copy.deepcopy(rows)
    [group] = unified._group_mdns_services(rows, record_sources, field_sources)
    assert group["mdnsRecords"] == before
    assert group["_networkInstance"] == (f"extpan:{scope}" if scope else None)
    assert set(record_sources) == set(field_sources) == {group["_unifiedRecordId"]}


@pytest.mark.parametrize(("dataset_id", "group_services"), [
    *((dataset_id, False) for dataset_id in DATASET_IDS), ("mdns_unified", True),
])
def test_committed_rows_use_one_browser_model_without_raw_file_dispatch(
    tmp_path, dataset_id, group_services,
):
    entry = _seed(tmp_path, dataset_id)
    if group_services:
        entry = _seed_mdns_omr_services(tmp_path)
    unified.build_unified_dataset(tmp_path, dataset_id)
    script = """
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {runAdaptor} from './src/js/tdash-adaptors.js';
import {buildDatasetRows} from './src/js/tdash-dataset.js';
import {buildDeviceProjections} from './src/js/tdash-device-projection.js';
import {createTopologyViewModel, resolveTopologyNodeId} from './src/js/tdash-topology-view-model.js';
const entry = JSON.parse(process.argv[1]);
const rawFiles = [JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))];
const {rows} = buildDatasetRows(entry, rawFiles);
const original = JSON.stringify(rows);
const result = runAdaptor({entry, rawFiles, rows});
assert.equal(result.nodeData.length, rows.length);
const view = createTopologyViewModel(result, buildDeviceProjections(rows));
for (const row of rows) {
  const id = row._unifiedRecordId;
  assert.equal(resolveTopologyNodeId(view, row), id);
  assert.equal(view.projectionByNodeId.get(id).deviceId, id);
  assert.deepEqual(result.rawByIdForDetails.get(id), row);
}
assert.equal(JSON.stringify(rows), original);
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(entry),
         str(tmp_path / entry["files"][0])],
        check=True, capture_output=True, text=True, cwd=ROOT, timeout=30,
    )


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
@pytest.mark.parametrize("empty", [False, True])
def test_complete_build_is_deterministic_and_no_op_preserves_every_artifact(tmp_path, dataset_id, empty):
    entry = _seed(tmp_path, dataset_id, empty=empty)
    result = unified.build_unified_dataset(tmp_path, dataset_id)
    assert result["materializationState"] == "complete"
    assert result["rowCount"] == (0 if empty else 3 if dataset_id == "ha_matter_ws_unified" else 1)
    assert result["noOp"] is False
    report = unified.read_generation(tmp_path, entry, verify_inputs=True)
    assert report["healthState"] == (
        "ineligible" if dataset_id == "mdns_unified" else
        "degraded" if dataset_id == "ha_matter_ws_unified" and empty else "complete"
    )
    assert report["generatedAt"] != SOURCE_TIME
    assert all(item.get("sourceObservedAt") == SOURCE_TIME
               for item in report["inputs"] if item["status"] == "selected")
    original = _artifacts(tmp_path, entry)
    second = unified.build_unified_dataset(tmp_path, dataset_id)
    assert second["noOp"] is True
    assert second["generationId"] == result["generationId"]
    assert original == _artifacts(tmp_path, entry)
    assert all(b"must-not-be-published" not in content and b"networkKey" not in content
               for content, _ in original.values())
    assert not list(tmp_path.glob(".td-unified-*.recovery"))
    assert {item["filename"] for sources in report["recordSources"].values()
            for item in sources} <= {item["file"] for item in entry["unified"]["inputs"]}
    assert all(not name.endswith("unified.json") for fields in report["fieldSources"].values()
               for origins in fields.values() for origin in origins for name in [origin["filename"]])


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_partial_is_opt_in_and_all_missing_is_failure(tmp_path, dataset_id):
    entry = _seed(tmp_path, dataset_id)
    missing = next(item["file"] for item in entry["unified"]["inputs"] if item["required"])
    (tmp_path / missing).unlink()
    with pytest.raises(unified.UnifiedDatasetError, match="Missing required"):
        unified.build_unified_dataset(tmp_path, dataset_id)
    result = unified.build_unified_dataset(tmp_path, dataset_id, allow_partial=True)
    assert result["materializationState"] == "partial"
    assert missing in result["coverage"]["missingRequired"]
    report = unified.read_generation(tmp_path, entry)
    assert report["materializationState"] == "partial"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(unified.UnifiedDatasetError, match="No usable"):
        unified.build_unified_dataset(empty, dataset_id, allow_partial=True)
    assert not (empty / entry["files"][0]).exists()


@pytest.mark.parametrize("payload", [
    b"invalid json", b'{"a":1,"a":2}', b"[NaN]", b"[Infinity]", b"[-Infinity]",
    b'[{"nested":1e9999}]', b"[1]", b"{}", b"[null]",
    b'[{"networkKey":"forbidden"}]',
])
def test_malformed_optional_input_cannot_replace_prior_generation(tmp_path, payload):
    entry = _seed(tmp_path, "otbr_cli_unified")
    unified.build_unified_dataset(tmp_path, entry["value"])
    before = _artifacts(tmp_path, entry)
    optional = tmp_path / "td-otbr-cli-router-table.json"
    optional.write_bytes(payload)
    with pytest.raises(ValueError):
        unified.build_unified_dataset(tmp_path, entry["value"], allow_partial=True)
    assert before == _artifacts(tmp_path, entry)
    unified.read_generation(tmp_path, entry)
    with pytest.raises(unified.UnifiedDatasetError, match="Stale Unified evidence"):
        unified.read_generation(tmp_path, entry, verify_inputs=True)


def test_parse_validates_without_serializing(monkeypatch):
    def unexpected_serialization(*args):
        pytest.fail("Parsing must not reserialize the document")

    monkeypatch.setattr(unified, "_json_bytes", unexpected_serialization)
    assert unified._parse(b'{"nested":[1.25,1e-9999,true,null]}', "test.json") == {
        "nested": [1.25, 0.0, True, None],
    }


def test_capability_cache_preserves_committed_and_invalid_classifications(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    unified.build_unified_dataset(tmp_path, entry["value"])
    service = SourceCapabilityService(probes={})
    filename = entry["files"][0]

    def compare():
        cached = asyncio.run(service.capabilities(tmp_path))
        fresh = asyncio.run(SourceCapabilityService(probes={}).capabilities(tmp_path))
        assert cached["files"] == fresh["files"]
        assert cached["sources"] == fresh["sources"]
        return cached["files"][filename]

    assert compare()["cached"]
    assert compare()["buildableFromCache"]
    original = tmp_path / entry["unified"]["inputs"][0]["file"]
    saved = original.read_bytes()
    original.write_bytes(b'{"duplicate":1,"duplicate":2}')
    assert compare()["cacheInputState"] == "invalid"
    original.write_bytes(saved)
    assert compare()["buildableFromCache"]
    companion = tmp_path / entry["unified"]["outcomeFile"]
    companion.unlink()
    assert not compare()["cached"]
    original.unlink()
    assert compare()["cacheInputState"] != "invalid"


def test_excluded_operational_metadata_is_never_opened(tmp_path, monkeypatch):
    entry = _seed(tmp_path, "otbr_restapi_unified")
    excluded = tmp_path / "td-otbr-restapi-actions-list.json"
    excluded.write_bytes(b"not valid JSON, with forbidden networkKey")
    original = Path.open

    def checked_open(path, *args, **kwargs):
        assert path != excluded
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    unified.build_unified_dataset(tmp_path, entry["value"])
    report = unified.read_generation(tmp_path, entry)
    assert report["excluded"] == [excluded.name]


def test_missing_identity_is_inspection_only_and_outcome_does_not_claim_complete(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    (tmp_path / "td-otbr-cli-thread-network-info.json").unlink()
    for item in entry["unified"]["inputs"]:
        (tmp_path / item["file"].replace(".json", ".network.json")).unlink(missing_ok=True)
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["healthState"] == "unavailable"
    outcome = json.loads((tmp_path / entry["unified"]["outcomeFile"]).read_text())
    identity = json.loads((tmp_path / entry["unified"]["identityFile"]).read_text())
    assert outcome["status"] == "degraded"
    assert identity["extPanId"] is None


def test_network_selection_never_assigns_unknown_scope_or_accepts_unobserved_network(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    first = entry["unified"]["inputs"][0]["file"]
    _save(tmp_path, first, [{"extAddress": "1111223344556677", "deviceLabel": "other"}], scope=OTHER_NETWORK)
    with pytest.raises(unified.UnifiedDatasetError, match="not been observed"):
        unified.build_unified_dataset(tmp_path, entry["value"], network="extpan:1111111111111111")
    result = unified.build_unified_dataset(tmp_path, entry["value"], network=NETWORK, allow_partial=True)
    assert result["rowCount"] == 1
    assert b"other" not in (tmp_path / entry["files"][0]).read_bytes()
    unknown = "td-otbr-cli-router-table.json"
    _save(tmp_path, unknown, [{"extAddress": "0011223344556677", "deviceLabel": "unknown"}], scope=None)
    result = unified.build_unified_dataset(tmp_path, entry["value"], network=NETWORK, allow_partial=True)
    assert result["rowCount"] == 2
    assert f"unknown-record-scope:{unknown}" in result["coverage"]["healthReasons"]


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_present_invalid_scope_aborts_instead_of_becoming_unknown(tmp_path, dataset_id):
    entry = _seed(tmp_path, dataset_id)
    first = entry["unified"]["inputs"][0]["file"]
    sidecar = tmp_path / first.replace(".json", ".network.json")
    payload = json.loads(sidecar.read_text())
    payload["snapshotSha256"] = "0" * 64
    sidecar.write_text(json.dumps(payload))
    with pytest.raises(unified.UnifiedDatasetError, match="Invalid scope binding"):
        unified.build_unified_dataset(tmp_path, dataset_id, allow_partial=True)


@pytest.mark.parametrize("boundary", range(1, 6))
@pytest.mark.parametrize("previous", [False, True])
def test_crash_at_every_replace_boundary_is_recovered_only_by_next_build(tmp_path, monkeypatch, boundary, previous):
    entry = _seed(tmp_path, "otbr_cli_unified")
    old_generation = None
    if previous:
        old_generation = unified.build_unified_dataset(tmp_path, entry["value"])["generationId"]
        before = _artifacts(tmp_path, entry)
    _save(tmp_path, entry["unified"]["inputs"][0]["file"],
          [{"extAddress": "0011223344556677", "deviceLabel": "changed"}])
    real_replace = unified.os.replace
    count = 0

    def crash_after_replace(source, target):
        nonlocal count
        real_replace(source, target)
        count += 1
        if count == boundary:
            raise KeyboardInterrupt("injected crash")

    with monkeypatch.context() as context:
        context.setattr(unified.os, "replace", crash_after_replace)
        with pytest.raises(KeyboardInterrupt, match="injected crash"):
            unified.build_unified_dataset(tmp_path, entry["value"])
    assert (tmp_path / f".td-unified-{entry['value']}.recovery").exists()
    if boundary < 5:
        with pytest.raises(unified.UnifiedDatasetError):
            unified.read_generation(tmp_path, entry)
    else:
        assert unified.read_generation(tmp_path, entry)["generationId"] != old_generation
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["generationId"] != old_generation
    assert unified.read_generation(tmp_path, entry, verify_inputs=True)["generationId"] == result["generationId"]
    assert not (tmp_path / f".td-unified-{entry['value']}.recovery").exists()
    if previous:
        assert _artifacts(tmp_path, entry) != before


def test_changed_input_before_commit_preserves_old_generation(tmp_path, monkeypatch):
    entry = _seed(tmp_path, "otbr_cli_unified")
    unified.build_unified_dataset(tmp_path, entry["value"])
    before = _artifacts(tmp_path, entry)
    first = entry["unified"]["inputs"][0]["file"]
    _save(tmp_path, first, [{"extAddress": "0011223344556677", "deviceLabel": "new"}])
    recheck = unified._recheck

    def mutate(directory, captured):
        if any(item.filename == first for item in captured):
            (directory / first).write_text("[]")
        return recheck(directory, captured)

    monkeypatch.setattr(unified, "_recheck", mutate)
    with pytest.raises(unified.UnifiedDatasetError, match="changed during build"):
        unified.build_unified_dataset(tmp_path, entry["value"])
    assert before == _artifacts(tmp_path, entry)


@pytest.mark.parametrize("previous", [False, True])
def test_interrupted_recovery_journal_write_never_replaces_public_artifacts(tmp_path, monkeypatch, previous):
    entry = _seed(tmp_path, "otbr_cli_unified")
    if previous:
        unified.build_unified_dataset(tmp_path, entry["value"])
        before = _artifacts(tmp_path, entry)
    _save(tmp_path, entry["unified"]["inputs"][0]["file"],
          [{"extAddress": "0011223344556677", "deviceLabel": "changed"}])
    original = unified._write

    def interrupted(path, content):
        if path.name == "commit.pending.json":
            path.write_bytes(b"{")
            raise KeyboardInterrupt("incomplete recovery journal")
        original(path, content)

    with monkeypatch.context() as context:
        context.setattr(unified, "_write", interrupted)
        with pytest.raises(KeyboardInterrupt):
            unified.build_unified_dataset(tmp_path, entry["value"])
    if previous:
        assert before == _artifacts(tmp_path, entry)
        unified.read_generation(tmp_path, entry)
    else:
        assert not (tmp_path / entry["files"][0]).exists()
    unified.build_unified_dataset(tmp_path, entry["value"])
    unified.read_generation(tmp_path, entry, verify_inputs=True)
    assert not (tmp_path / f".td-unified-{entry['value']}.recovery").exists()


def test_changed_input_during_read_is_rejected(tmp_path, monkeypatch):
    path = _save(tmp_path, "changing.json", [{"extAddress": "0011223344556677"}], scope=None)
    original = Path.stat

    def changed_stat(current, *args, **kwargs):
        if current == path:
            os.utime(path, ns=(1_767_225_600_000_000_000, 1_767_225_601_000_000_000))
        return original(current, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", changed_stat)
    with pytest.raises(unified.UnifiedDatasetError, match="Changing cached input"):
        unified._read_stable(tmp_path, path.name)


def test_committed_report_changed_during_read_is_rejected_without_repair(tmp_path, monkeypatch):
    entry = _seed(tmp_path, "otbr_cli_unified")
    unified.build_unified_dataset(tmp_path, entry["value"])
    report_file = entry["unified"]["reportFile"]
    original = unified._read_stable
    reads = 0

    def changing_report(directory, filename):
        nonlocal reads
        captured = original(directory, filename)
        if filename == report_file:
            reads += 1
            if reads == 1:
                marker = json.loads(captured.content)
                marker["generatedAt"] = SOURCE_TIME
                (directory / filename).write_text(json.dumps(marker))
        return captured

    monkeypatch.setattr(unified, "_read_stable", changing_report)
    with pytest.raises(unified.UnifiedDatasetError, match="changed during build"):
        unified.read_generation(tmp_path, entry)


def test_newer_checkpoint_is_not_an_input(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    first = entry["unified"]["inputs"][0]["file"]
    checkpoint = first.replace(".json", ".partial.json")
    (tmp_path / checkpoint).write_bytes(b"malformed checkpoint must not be read")
    unified.build_unified_dataset(tmp_path, entry["value"])
    assert checkpoint not in [item["filename"] for item in unified.read_generation(tmp_path, entry)["inputs"]]
    with pytest.raises(web.HTTPNotFound):
        td_webserver._resolve_and_validate("td-otbr-cli-unified.partial.json", tmp_path)


def test_independent_process_builds_share_one_advisory_lock_and_generation(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    program = (
        "import json,sys; from pathlib import Path; "
        "from td_unified_dataset import build_unified_dataset; "
        "print('ready',flush=True); "
        "print(json.dumps(build_unified_dataset(Path(sys.argv[1]),'otbr_cli_unified')),flush=True)"
    )
    processes = []
    with (tmp_path / ".td-unified.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            for _ in range(2):
                process = subprocess.Popen(
                    [sys.executable, "-c", program, str(tmp_path)],
                    cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                processes.append(process)
                assert process.stdout.readline().strip() == "ready"
                assert process.poll() is None
            assert not (tmp_path / entry["files"][0]).exists()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    assert len({result["generationId"] for result in results}) == 1
    assert sorted(result["noOp"] for result in results) == [False, True]
    unified.read_generation(tmp_path, entry, verify_inputs=True)


@pytest.mark.parametrize("filename", [
    "td-otbr-cli-unified.json", "td-otbr-cli-unified-thread-network-info.json",
    "td-otbr-cli-unified.network.json", "td-otbr-cli-unified.outcome.json",
])
def test_readers_reject_every_mixed_artifact_without_repairs(tmp_path, filename):
    entry = _seed(tmp_path, "otbr_cli_unified")
    unified.build_unified_dataset(tmp_path, entry["value"])
    (tmp_path / filename).write_bytes(b"[]")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    with pytest.raises(unified.UnifiedDatasetError, match="Mixed or incomplete"):
        unified.read_generation(tmp_path, entry)
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}


def test_credential_bearing_generation_is_an_explicit_read_error(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    unified.build_unified_dataset(tmp_path, entry["value"])
    row_file = tmp_path / entry["files"][0]
    rows = json.loads(row_file.read_text())
    rows[0]["networkKey"] = "forbidden"
    content = unified._json_bytes(rows)
    row_file.write_bytes(content)
    report_file = tmp_path / entry["unified"]["reportFile"]
    report = json.loads(report_file.read_text())
    report["snapshotSha256"] = unified._digest(content)
    report["artifactDigests"][row_file.name] = unified._digest(content)
    report_file.write_text(json.dumps(report))
    with pytest.raises(unified.UnifiedDatasetError, match="Unsafe Unified generation"):
        unified.read_generation(tmp_path, entry)


def test_same_file_identity_duplicates_remain_visible(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    first = entry["unified"]["inputs"][0]["file"]
    _save(tmp_path, first, [
        {"extAddress": "0011223344556677", "deviceLabel": "first"},
        {"extAddress": "0011223344556677", "deviceLabel": "second"},
    ])
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["rowCount"] >= 2
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    assert "second" in {row["deviceLabel"] for row in rows}
    assert any(conflict.get("incoming") == "first"
               for row in rows for conflict in row.get("_merge_conflicts", []))
    report = unified.read_generation(tmp_path, entry)
    references = [origin["recordId"] for origins in report["recordSources"].values()
                  for origin in origins if origin["filename"] == first]
    assert len(references) == len(set(references)) == 2


@pytest.mark.parametrize("filename", [
    "td-otbr-restapi-diagnostics.json",
    "td-otbr-restapi-diagnostics-list.json",
    "td-otbr-restapi-diagnostics-fetch-all.json",
    "td-otbr-restapi-mesh-diagnostics-fetch-all.json",
])
@pytest.mark.parametrize("dataset_id", ["otbr_restapi_unified", "multi_source_unified"])
def test_rest_diagnostic_observations_merge_without_identity_ambiguity(tmp_path, filename, dataset_id):
    _seed(tmp_path, "otbr_restapi_unified")
    observations = [
        {"id": "observation-1", "type": "networkDiagnostics",
         "extAddress": "0011223344556677", "rloc16": "0x1000",
         "created": SOURCE_TIME, "vendorName": "vendor",
         "routerNeighbors": [{"extAddress": "8899aabbccddeeff", "rloc16": "0x2000"}]},
        {"id": "observation-2", "type": "networkDiagnostics",
         "extAddress": "0011223344556677", "rloc16": "0x1000",
         "created": "2026-01-01T00:01:00+00:00", "vendorModel": "model",
         "childTable": [{"extAddress": "1122334455667788", "rloc16": "0x1001"}]},
    ]
    _save(tmp_path, filename, {"data": observations})
    entry = _entry(dataset_id)
    unified.build_unified_dataset(tmp_path, dataset_id, allow_partial=True)
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    assert len(rows) == 1
    row = rows[0]
    assert row["deviceLabel"] == "router"
    assert row["vendorName"] == "vendor"
    assert row["vendorModel"] == "model"
    assert row["routerNeighbors"] == observations[0]["routerNeighbors"]
    assert row["childTable"] == observations[1]["childTable"]
    assert not any(conflict["path"] == "_merge_identity_ambiguity"
                   for conflict in row.get("_merge_conflicts", []))
    report = unified.read_generation(tmp_path, entry, verify_inputs=True)
    origins = report["recordSources"][row["_unifiedRecordId"]]
    references = [origin["recordId"] for origin in origins if origin["filename"] == filename]
    assert len(references) == len(set(references)) == 2
    assert report["fieldSources"][row["_unifiedRecordId"]]["vendorName"] == [
        {"filename": filename, "recordId": references[0]},
    ]
    assert unified.build_unified_dataset(
        tmp_path, dataset_id, allow_partial=True,
    )["noOp"] is True


@pytest.mark.parametrize("previous_contract", [
    "unified-assembly-v2", "unified-assembly-v3", "unified-assembly-v4", "unified-assembly-v5",
    "unified-assembly-v6", "unified-assembly-v7",
])
def test_previous_assembly_generation_remains_readable_but_explicit_build_upgrades(
    tmp_path, monkeypatch, previous_contract,
):
    entry = _seed(tmp_path, "otbr_restapi_unified")
    current_contract = unified.BUILDER_CONTRACT
    monkeypatch.setattr(unified, "BUILDER_CONTRACT", previous_contract)
    previous = unified.build_unified_dataset(tmp_path, entry["value"])
    monkeypatch.setattr(unified, "BUILDER_CONTRACT", current_contract)
    assert unified.read_generation(tmp_path, entry)["generationId"] == previous["generationId"]
    upgraded = unified.build_unified_dataset(tmp_path, entry["value"])
    assert upgraded["noOp"] is False
    assert upgraded["generationId"] != previous["generationId"]
    assert unified.build_unified_dataset(tmp_path, entry["value"])["noOp"] is True


@pytest.mark.parametrize("records", [
    [{"rloc16": "0x1000", "id": "first"}, {"rloc16": "0x1000", "id": "second"}],
    [{"rloc16": "0x1000", "extAddress": "0000000000000000", "id": name}
     for name in ("first", "second")],
    [{"rloc16": "0x1000"}, {"rloc16": "0x1000", "extAddress": "0011223344556677"}],
    [{"extAddress": "0011223344556677",
      "matter": {"matterId": fabric + "-0000000000000001"}}
     for fabric in ("1111222233334444", "9999222233334444")],
    [{"extAddress": ext, "rloc16": "0x1000"}
     for ext in ("0011223344556677", "8899aabbccddeeff")],
])
def test_diagnostic_observations_do_not_collapse_uncertain_or_conflicting_identities(records):
    rows, origins = unified.merge_cached_records(
        [("td-otbr-restapi-diagnostics.json", records)], NETWORK[7:],
    )
    assert len(rows) == 2
    assert all(len(contributors) == 1 for contributors in origins.values())


def test_diagnostic_observation_cannot_resolve_another_same_file_collision():
    rows, _ = unified.merge_cached_records([
        ("td-otbr-cli-networkdiag-fetch-all.json", [
            {"extAddress": "0011223344556677", "deviceLabel": "first"},
            {"extAddress": "0011223344556677", "deviceLabel": "second"},
        ]),
        ("td-otbr-restapi-diagnostics.json", [
            {"extAddress": "0011223344556677", "id": "observation"},
        ]),
    ], NETWORK[7:])
    assert len(rows) == 3
    assert any(conflict["path"] == "_merge_identity_ambiguity"
               for row in rows for conflict in row.get("_merge_conflicts", []))


def test_json_api_attributes_and_matter_fields_survive_without_network_calls(tmp_path, monkeypatch):
    entry = _seed(tmp_path, "otbr_restapi_unified")
    filename = entry["unified"]["inputs"][0]["file"]
    record = {"id": "device", "attributes": {"extAddress": "0011223344556677",
              "matter": {"compressedFabricId": "1234567890abcdef", "nodeId": "0000000000000001",
                         "endpoints": [{"endpointId": 1, "deviceTypes": [256]}]},
              "powerSources": [{"endpointId": 1, "type": "battery"}]}}
    _save(tmp_path, filename, {"data": [record]})
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("No subprocesses allowed"))
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["rowCount"] == 1
    row = json.loads((tmp_path / entry["files"][0]).read_text())[0]
    assert row["matter"]["endpoints"] == record["attributes"]["matter"]["endpoints"]
    assert row["powerSources"] == record["attributes"]["powerSources"]


def test_raw_mtime_fallback_is_explicit_and_health_verification_rejects_retiming(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    first = entry["unified"]["inputs"][0]["file"]
    path = _save(tmp_path, first, [{"extAddress": "0011223344556677"}])
    unified.build_unified_dataset(tmp_path, entry["value"])
    report = unified.read_generation(tmp_path, entry)
    assert report["inputs"][0]["timeProvenance"] == "raw-file-mtime"
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))
    unified.read_generation(tmp_path, entry)
    with pytest.raises(unified.UnifiedDatasetError, match="Stale Unified evidence time"):
        unified.read_generation(tmp_path, entry, verify_inputs=True)


def test_future_source_time_is_unavailable_not_replaced_by_build_time(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    first = entry["unified"]["inputs"][0]["file"]
    _save(tmp_path, first, [{"extAddress": "0011223344556677", "observedAt": "2999-01-01T00:00:00Z"}])
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert f"unavailable-source-time:{first}" in result["coverage"]["healthReasons"]
    report = unified.read_generation(tmp_path, entry)
    assert report["inputs"][0]["sourceObservedAt"] is None
    assert report["inputs"][0]["timeProvenance"] == "invalid-source-time"


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_nonempty_but_unusable_records_do_not_claim_success(tmp_path, dataset_id):
    entry = _seed(tmp_path, dataset_id)
    first = entry["unified"]["inputs"][0]
    _save(tmp_path, first["file"], {"data": [{}]} if first["extractor"] == "json-api" else [{}])
    expected_error = "commissioned Matter" if dataset_id == "ha_matter_ws_unified" else "identit"
    with pytest.raises(unified.UnifiedDatasetError, match=expected_error):
        unified.build_unified_dataset(tmp_path, dataset_id, allow_partial=True)
    assert not (tmp_path / entry["files"][0]).exists()


def test_summary_counts_all_canonical_relationship_containers(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    first = entry["unified"]["inputs"][0]["file"]
    _save(tmp_path, first, [{
        "extAddress": "0011223344556677",
        "links1": [{"rloc16": "0x2000"}],
        "childTable": [{"rloc16": "0x1001", "tableAttempt": {"status": "success"}}],
        "routerNeighbors": [{"rloc16": "0x3000"}],
        "route": {"routeData": [{"routeId": 4, "linkQualityIn": 3}]},
    }])
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["linkCount"] == 4
    assert unified.read_generation(tmp_path, entry)["linkCount"] == 4


def test_capability_inspection_is_local_read_only_and_reports_invalid_generation(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = asyncio.run(SourceCapabilityService(probes={}).capabilities(tmp_path))
    file_info = result["files"][entry["files"][0]]
    assert file_info["cached"] is False
    assert file_info["buildableFromCache"] is True
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    unified.build_unified_dataset(tmp_path, entry["value"])
    assert unified.inspect_unified_cache(tmp_path, entry)["cached"] is True
    committed = asyncio.run(SourceCapabilityService(probes={}).capabilities(tmp_path))
    scope = committed["files"][entry["files"][0]]["networkInstance"]
    assert scope["extPanId"] == NETWORK[7:]
    assert scope["provenance"] == "observed"
    (tmp_path / entry["files"][0]).write_text("[]")
    info = unified.inspect_unified_cache(tmp_path, entry)
    assert info["cached"] is False and info["buildableFromCache"] is True
    assert any("Mixed or incomplete" in reason for reason in info["cacheReasons"])
    assert unified.build_unified_dataset(tmp_path, entry["value"])["noOp"] is False
    unified.read_generation(tmp_path, entry)


def test_server_actions_are_processing_only_with_static_bound_companions():
    for dataset_id in DATASET_IDS:
        entry = _entry(dataset_id)
        action = td_webserver.get_file_action(entry["files"][0])
        assert action.action == ["unify-dataset", "--dataset", dataset_id, "--allow-partial", "--json"]
        assert action.force_async and action.action_cost_s * 1.5 == 60
        for filename in [*unified._artifact_names(entry)[1:], entry["unified"]["reportFile"]]:
            assert td_webserver.get_file_action(filename).action == "STATIC"


def test_http_partial_header_includes_revalidation_and_refuses_mixed_generation(tmp_path):
    entry = _seed(tmp_path, "otbr_cli_unified")
    (tmp_path / entry["unified"]["inputs"][0]["file"]).unlink()
    unified.build_unified_dataset(tmp_path, entry["value"], allow_partial=True)
    path = tmp_path / entry["files"][0]
    action = td_webserver.get_file_action(path.name)
    response = td_webserver._build_file_response(path, action)
    assert response.headers["X-TD-Materialization-State"] == "partial"
    request = MagicMock(headers={"If-None-Match": response.headers["ETag"]})
    revalidation = td_webserver._build_file_response(path, action, request)
    assert revalidation.status == 304
    assert revalidation.headers["X-TD-Materialization-State"] == "partial"
    path.write_text("[]")
    with pytest.raises(web.HTTPConflict):
        td_webserver._build_file_response(path, action, request)


@pytest.mark.parametrize("state", ["missing", "invalid", "stale"])
def test_cache_only_never_materializes_or_repairs_unified_files(tmp_path, monkeypatch, state):
    entry = _seed(tmp_path, "otbr_cli_unified")
    if state != "missing":
        unified.build_unified_dataset(tmp_path, entry["value"])
        if state == "invalid":
            (tmp_path / entry["files"][0]).write_text("[]")
        else:
            os.utime(tmp_path / entry["files"][0], ns=(1, 1))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    async def forbidden(*args, **kwargs):
        pytest.fail("Cache Only must not dispatch any processing")

    monkeypatch.setattr(td_webserver, "run_td_cli", forbidden)
    request = make_data_request(
        entry["files"][0], make_webserver_app(tmp_path),
        cache_control="only-if-cached, max-age=1",
    )
    with pytest.raises((web.HTTPNotFound, web.HTTPConflict)):
        asyncio.run(td_webserver.handle_data_api(request))
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}


@pytest.mark.parametrize("result_state", ["partial", "invalid-report", "subprocess-failure"])
def test_server_job_verifies_report_before_success_and_retains_partial_metadata(tmp_path, monkeypatch, result_state):
    entry = _seed(tmp_path, "otbr_cli_unified")
    (tmp_path / entry["unified"]["inputs"][0]["file"]).unlink()
    reset_webserver_state()

    async def fake_cli(arguments, data_dir, *, timeout_s, **kwargs):
        assert arguments == ["unify-dataset", "--dataset", entry["value"], "--allow-partial", "--json"]
        assert timeout_s == 60
        if result_state == "subprocess-failure":
            return 1
        unified.build_unified_dataset(data_dir, entry["value"], allow_partial=True)
        if result_state == "invalid-report":
            (data_dir / entry["unified"]["reportFile"]).write_text("{}")
        return 0

    monkeypatch.setattr(td_webserver, "run_td_cli", fake_cli)

    async def run_job():
        response = await td_webserver.handle_data_api(make_data_request(
            entry["files"][0], make_webserver_app(tmp_path),
            no_cache=True,
        ))
        assert response.status == 202
        job_id = json.loads(response.body)["job_id"]
        await td_webserver._job_runtime_registry[job_id].task
        return td_webserver._job_registry[job_id]

    try:
        job = asyncio.run(run_job())
        assert job.status == ("done" if result_state == "partial" else "error")
        if result_state == "partial":
            assert job.result["materializationState"] == "partial"
            assert job.result["coverage"]["missingRequired"]
        else:
            assert job.detail
    finally:
        reset_webserver_state()


@pytest.mark.parametrize("dataset_id", DATASET_IDS)
def test_cli_json_is_one_object_and_forwards_effective_datadir(tmp_path, dataset_id):
    entry = _seed(tmp_path, dataset_id)
    result = subprocess.run(
        [sys.executable, "-m", "td_cli", "--datadir", str(tmp_path),
         "unify-dataset", "--dataset", entry["value"], "--json"],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["datasetId"] == entry["value"]
    assert summary["materializationState"] == "complete"
    unified.read_generation(tmp_path, entry)


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_all_builds_five_datasets_and_repeat_preserves_artifacts(tmp_path, json_output):
    dataset_ids = (*DATASET_IDS, "multi_source_unified")
    for dataset_id in DATASET_IDS:
        _seed(tmp_path, dataset_id)
    command = [
        sys.executable, "-m", "td_cli", "--datadir", str(tmp_path),
        "unify-dataset", "--dataset", "all",
    ]
    if json_output:
        command.append("--json")
    artifacts = {}
    for repeat in (False, True):
        result = subprocess.run(
            command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        if json_output:
            summaries = json.loads(result.stdout)
            assert [item["datasetId"] for item in summaries] == list(dataset_ids)
            assert all(item["materializationState"] == "complete" for item in summaries)
            assert all(item["noOp"] is repeat for item in summaries)
        else:
            lines = result.stdout.splitlines()
            assert lines[:3] == [
                "Thread Network Topology CLI", "", "Command: unify-dataset, sub-command: ",
            ]
            lines = lines[3:]
            assert len(lines) == len(dataset_ids)
            assert all(line.startswith(f"{dataset_id}: complete; ")
                       for line, dataset_id in zip(lines, dataset_ids, strict=True))
        current = {}
        for dataset_id in dataset_ids:
            entry = _entry(dataset_id)
            unified.read_generation(tmp_path, entry, verify_inputs=True)
            current[dataset_id] = _artifacts(tmp_path, entry)
        if repeat:
            assert current == artifacts
        artifacts = current


@pytest.mark.parametrize("allow_partial", [False, True])
def test_cli_all_requires_explicit_partial_and_forwards_network(
    tmp_path, capsys, caplog, allow_partial,
):
    for dataset_id in DATASET_IDS:
        _seed(tmp_path, dataset_id)
    missing = next(item["file"] for item in _entry("otbr_cli_unified")["unified"]["inputs"]
                   if item["required"])
    (tmp_path / missing).unlink()
    arguments = [
        "--datadir", str(tmp_path), "--dataset", "all", "--network", NETWORK, "--json",
    ]
    if allow_partial:
        arguments.append("--allow-partial")
    assert unified.main(arguments) == (0 if allow_partial else 1)
    output = capsys.readouterr().out
    if allow_partial:
        summaries = json.loads(output)
        assert len(summaries) == 5
        assert [item["datasetId"] for item in summaries] == [
            *DATASET_IDS, "multi_source_unified",
        ]
        assert summaries[0]["materializationState"] == "partial"
        assert summaries[-1]["materializationState"] == "partial"
        for dataset_id in (*DATASET_IDS, "multi_source_unified"):
            report = unified.read_generation(tmp_path, _entry(dataset_id), verify_inputs=True)
            assert report["networkInstance"] == (None if dataset_id == "mdns_unified" else NETWORK)
    else:
        assert output == ""
        assert "Missing required" in caplog.text
        assert not (tmp_path / _entry("multi_source_unified")["files"][0]).exists()


def test_cli_all_stops_on_invalid_input_without_rolling_back_prior_builds(
    tmp_path, capsys, caplog,
):
    for dataset_id in DATASET_IDS:
        _seed(tmp_path, dataset_id)
    rest = _entry("otbr_restapi_unified")
    invalid = next(item["file"] for item in rest["unified"]["inputs"] if item["required"])
    (tmp_path / invalid).write_text("{", encoding="utf-8")
    assert unified.main(["--datadir", str(tmp_path), "--dataset", "all", "--json"]) == 1
    assert capsys.readouterr().out == ""
    assert "Invalid cached JSON" in caplog.text
    unified.read_generation(tmp_path, _entry("otbr_cli_unified"), verify_inputs=True)
    for dataset_id in (*DATASET_IDS[1:], "multi_source_unified"):
        assert not (tmp_path / _entry(dataset_id)["files"][0]).exists()


@pytest.mark.parametrize("arguments", [
    ["--dataset", "otbr_cli_mesh"], ["--dataset", "otbr_cli_unified", "--output", "elsewhere.json"],
    ["--dataset", "otbr_cli_unified", "--network", "extpan:ABCDEF1234567890"],
    ["--dataset", "otbr_cli_unified", "--network", "extpan:0000000000000000"],
    ["--dataset", "otbr_cli_unified", "--refresh"], ["--dataset", "otbr_cli_unified", "--host", "host"],
])
def test_cli_rejects_arbitrary_inputs_live_flags_and_output_overrides(tmp_path, arguments):
    with pytest.raises(SystemExit) as exc:
        unified.main(["--datadir", str(tmp_path), *arguments])
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(version="future"),
    lambda r: r.update(reportFile="../report.json"),
    lambda r: r.update(unexpected=True),
    lambda r: r["inputs"].append(copy.deepcopy(r["inputs"][0])),
    lambda r: r["inputs"][0].update(file="td-otbr-cli-unified.json"),
    lambda r: r["inputs"][0].update(file="td-otbr-restapi-actions-list.json"),
    lambda r: r["inputs"][0].update(extractor="guess"),
    lambda r: r["inputs"][0].update(required="true"),
    lambda r: r["inputs"][0].update(role="identity"),
])
def test_invalid_unified_recipes_rejected_in_both_runtimes(mutation):
    catalog = load_dataset_catalog()
    recipe = resolve_dataset(catalog, "otbr_cli_unified")["unified"]
    mutation(recipe)
    with pytest.raises(ValueError):
        validate_dataset_catalog(catalog)
    module = (ROOT / "src/js/tdash-dataset-registry.js").as_uri()
    result = subprocess.run([
        "node", "--input-type=module", "-e",
        f'import {{validateDatasetCatalog}} from "{module}"; '
        'try { validateDatasetCatalog(JSON.parse(process.argv[1])); process.exit(1); } '
        'catch(error) { console.log(error.message); }', json.dumps(catalog),
    ], capture_output=True, text=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def _ha_native_fixture():
    return json.loads((ROOT / "tests/fixtures/ha_matter_ws_thread_network_schema13.json").read_text())


def _ha_wrapper(field, value):
    source = {"borderRouters": "thread-border-routers", "topology": "network-topology"}[field]
    return {"schemaVersion": "1.0.0", "source": f"ha-matter-ws-{source}",
            "observedAt": SOURCE_TIME, "uri": "ws://not-copied.invalid/?token=not-published",
            field: value}


def _seed_ha(directory, *, empty=False):
    entry = _entry("ha_matter_ws_unified")
    matter = {"matterId": "1111222233334444-0000000000000001", "nodeId": 1,
              "deviceLabel": "commissioned router"}
    thread = {"matter": matter, "extAddress": "0011223344556677",
              "extPanId": NETWORK[7:], "rloc16": "0x1000", "role": "router",
              "sourceObservedAt": SOURCE_TIME, "type": "threadDevice",
              "thread": {"extAddress": "0011223344556677", "extendedPanId": NETWORK[7:],
                         "routingRole": "router"},
              "powerSources": [{"endpointId": 0, "batteryPercent": 0}],
              "endpoints": [{"endpointId": 0, "bridged": False}]}
    non_thread = {"matter": {"matterId": "1111222233334444-0000000000000002", "nodeId": 2},
                  "type": "matterDevice", "sourceObservedAt": SOURCE_TIME}
    graph = {"collected_at": 1_767_225_600_000, "nodes": [], "connections": []}
    if not empty:
        graph["nodes"] = [
            {"id": "native-router", "kind": "matter", "network_type": "thread",
             "ext_address": thread["extAddress"], "ext_pan_id": NETWORK[7:],
             "rloc16": 4096, "role": "router"},
            {"id": "ap", "kind": "wifi_ap", "network_type": "wifi", "ssid": "WiFi"},
        ]
        graph["connections"] = [{"source": "native-router", "target": "ap",
                                 "network": "wifi", "strength": "strong"}]
    _save(directory, "td-ha-matter-ws-devices-fetch-all.json", [] if empty else [thread, non_thread])
    _save(directory, "td-ha-matter-ws-topology.json", [] if empty else [thread])
    _save(directory, "td-ha-matter-ws-thread-border-routers.json", _ha_wrapper(
        "borderRouters", [] if empty else [{
            "extAddressHex": thread["extAddress"], "extendedPanIdHex": NETWORK[7:],
            "networkName": "test", "addresses": ["2001:db8::1"], "sources": ["meshcop"],
            "lastSeen": 1_767_225_600_000,
        }],
    ))
    _save(directory, "td-ha-matter-ws-network-topology.json", _ha_wrapper("topology", graph))
    for item in entry["unified"]["inputs"]:
        if item["role"] != "outcome":
            continue
        if item["file"] == "td-ha-matter-ws-collection.outcome.json":
            payload = {"source": "ha-matter-ws", "status": "success", "nodeErrors": [],
                       "nodeCount": 0 if empty else 2, "normalizedNodeCount": 0 if empty else 2,
                       "finalFiles": ["td-ha-matter-ws-devices-fetch-all.json", "td-ha-matter-ws-topology.json"]}
        else:
            routers = "border-routers" in item["file"]
            payload = {"source": "ha-matter-ws", "status": "complete",
                       "command": "get_thread_border_routers" if routers else "get_network_topology",
                       "finalFile": item["file"].replace(".outcome.json", ".json"),
                       "itemCount" if routers else "nodeCount": 0 if empty else 1 if routers else 2}
            if not routers:
                payload["connectionCount"] = 0 if empty else 1
        _save(directory, item["file"], {**payload, "startedAt": SOURCE_TIME, "completedAt": SOURCE_TIME})
    return entry


def test_ha_inventory_preserves_non_thread_members_and_all_safe_device_fields():
    inventory = [{
        "matter": {"matterId": "1111222233334444-0000000000000001", "nodeId": 1,
                   "endpoints": [{"endpointId": 0, "bridged": False}], "available": False,
                   "vendorModel": "model", "commissioned": True},
        "thread": {"extAddress": "0011223344556677", "extendedPanId": "1234567890ABCDEF",
                   "routingRole": "end_device"},
        "powerSources": [{"endpointId": 0, "batteryPercent": 0, "rawAttributes": {"voltage": None}}],
        "generalDiagnostics": {"rebootCount": 0, "uptime": 0, "faults": []},
        "networkInterfaces": [{"name": "eth0", "operational": False}],
        "diagnosticCoverage": {"thread": None},
    }, {
        "matter": {"matterId": "1111222233334444-0000000000000002", "nodeId": 2},
        "endpoints": [{"endpointId": 1, "deviceTypes": ["light"]}],
        "powerSources": [],
    }]
    before = copy.deepcopy(inventory)
    thread, non_thread = normalize_inventory(inventory)
    assert inventory == before
    for field in ("powerSources", "generalDiagnostics", "networkInterfaces", "diagnosticCoverage"):
        assert thread[field] == inventory[0][field]
    assert thread["matter"]["endpoints"] == inventory[0]["matter"]["endpoints"]
    assert thread["extPanId"] == NETWORK[7:]
    assert thread["isRouter"] is False
    assert thread["available"] is False
    assert non_thread["type"] == "matterDevice"
    assert non_thread["endpoints"] == inventory[1]["endpoints"]
    assert not any(key in non_thread for key in ("isRouter", "isBorderRouter", "isLeader", "isReed"))


def test_ha_primary_preserves_inventory_and_native_links_without_assigning_non_thread_scope(tmp_path):
    entry = _seed_ha(tmp_path)
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    report = unified.read_generation(tmp_path, entry, verify_inputs=True)
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    assert result["rowCount"] == 3 and result["linkCount"] == 1
    thread = next(row for row in rows if row.get("nativeNodeIds") == ["native-router"])
    access_point = next(row for row in rows if row.get("nativeNodeIds") == ["ap"])
    non_thread = next(row for row in rows if row.get("type") == "matterDevice")
    assert thread["powerSources"] == [{"endpointId": 0, "batteryPercent": 0}]
    assert thread["endpoints"] == [{"endpointId": 0, "bridged": False}]
    assert access_point["_networkInstance"] is None and non_thread["_networkInstance"] is None
    [link] = thread["nativeRelationships"]
    assert link["sourceId"] == thread["_unifiedRecordId"]
    assert link["targetId"] == access_point["_unifiedRecordId"]
    assert "isRouter" not in non_thread and "isRouter" not in access_point
    assert report["coverage"]["commissionedInventory"]["selectedRecordCount"] == 2
    assert report["coverage"]["unresolvedNativeRelationships"] == []
    assert report["networkInstance"] == NETWORK and result["healthState"] == "complete"
    assert {origin["filename"] for origin in report["fieldSources"][thread["_unifiedRecordId"]]["powerSources"]} >= {
        "td-ha-matter-ws-devices-fetch-all.json",
    }


def test_ha_dashboard_enriches_without_duplicate_members_or_substituting_missing_inventory(tmp_path):
    entry = _seed_ha(tmp_path)
    inventory_file = tmp_path / "td-ha-matter-ws-devices-fetch-all.json"
    devices = json.loads(inventory_file.read_text())
    dashboard = {"schemaVersion": "1.0.0", "devices": devices,
                 "diagnostics": [devices[0]], "meshDiagnostics": [devices[0]],
                 "topology": [devices[0]]}
    _save(tmp_path, "td-ha-matter-ws-dashboard.json", dashboard)
    complete = unified.build_unified_dataset(tmp_path, entry["value"])
    assert complete["rowCount"] == 3
    report = unified.read_generation(tmp_path, entry)
    dashboard_input = next(item for item in report["inputs"] if item["role"] == "projection")
    assert dashboard_input["selectedRecordCount"] == 2
    inventory_file.unlink()
    with pytest.raises(unified.UnifiedDatasetError, match="Missing required"):
        unified.build_unified_dataset(tmp_path, entry["value"])
    partial = unified.build_unified_dataset(tmp_path, entry["value"], allow_partial=True)
    assert partial["materializationState"] == "partial"
    assert partial["coverage"]["commissionedInventory"]["status"] == "missing"


def test_ha_native_graph_read_time_does_not_refresh_original_graph_evidence(tmp_path):
    entry = _seed_ha(tmp_path)
    filename = "td-ha-matter-ws-network-topology.json"
    payload = json.loads((tmp_path / filename).read_text())
    payload["topology"]["collected_at"] = 1_767_139_200_000
    _save(tmp_path, filename, payload)
    unified.build_unified_dataset(tmp_path, entry["value"])
    report = unified.read_generation(tmp_path, entry)
    metadata = next(item for item in report["inputs"] if item["filename"] == filename)
    assert metadata["sourceObservedAt"] == "2025-12-31T00:00:00+00:00"
    assert metadata["timeProvenance"] == "embedded"
    assert metadata["sourceObservedAt"] != payload["observedAt"]
    payload["observedAt"] = "2026-02-01T00:00:00+00:00"
    _save(tmp_path, filename, payload)
    unified.build_unified_dataset(tmp_path, entry["value"])
    second = unified.read_generation(tmp_path, entry)
    assert next(item for item in second["inputs"] if item["filename"] == filename)["sourceObservedAt"] == metadata["sourceObservedAt"]


@pytest.mark.parametrize("filename", [
    "td-ha-matter-ws-thread-border-routers.json",
    "td-ha-matter-ws-network-topology.json",
])
def test_ha_oversized_native_time_rejects_input_and_preserves_generation(tmp_path, filename):
    entry = _seed_ha(tmp_path)
    unified.build_unified_dataset(tmp_path, entry["value"])
    before = _artifacts(tmp_path, entry)
    payload = json.loads((tmp_path / filename).read_text())
    if "borderRouters" in payload:
        payload["borderRouters"][0]["lastSeen"] = 10**400
    else:
        payload["topology"]["collected_at"] = 10**400
    _save(tmp_path, filename, payload)
    with pytest.raises(unified.UnifiedDatasetError, match="Invalid cached HA product"):
        unified.build_unified_dataset(tmp_path, entry["value"])
    assert _artifacts(tmp_path, entry) == before


@pytest.mark.parametrize("filename", [
    "td-ha-matter-ws-collection.outcome.json",
    "td-ha-matter-ws-thread-border-routers.outcome.json",
    "td-ha-matter-ws-network-topology.outcome.json",
])
def test_ha_original_failed_outcomes_degrade_evidence_without_hiding_usable_rows(tmp_path, filename):
    entry = _seed_ha(tmp_path)
    payload = json.loads((tmp_path / filename).read_text())
    payload["status"] = "failed"
    _save(tmp_path, filename, payload)
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["materializationState"] == "complete"
    assert result["healthState"] == "degraded"
    assert f"incomplete-outcome:{filename}" in result["coverage"]["healthReasons"]
    before = _artifacts(tmp_path, entry)
    payload["status"] = True
    _save(tmp_path, filename, payload)
    with pytest.raises(unified.UnifiedDatasetError, match="Invalid cached HA outcome"):
        unified.build_unified_dataset(tmp_path, entry["value"], allow_partial=True)
    assert before == _artifacts(tmp_path, entry)


def test_ha_multiple_networks_need_observed_selection_and_never_assign_unknown_rows(tmp_path):
    entry = _seed_ha(tmp_path)
    filename = "td-ha-matter-ws-thread-border-routers.json"
    payload = json.loads((tmp_path / filename).read_text())
    payload["borderRouters"][0]["extendedPanIdHex"] = OTHER_NETWORK[7:]
    _save(tmp_path, filename, payload, scope=OTHER_NETWORK)
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["healthState"] == "unavailable"
    identity = json.loads((tmp_path / entry["unified"]["identityFile"]).read_text())
    assert identity["extPanId"] is None and identity["provenance"] == "unknown"
    selected = unified.build_unified_dataset(tmp_path, entry["value"], network=NETWORK, allow_partial=True)
    assert selected["materializationState"] == "partial"
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    assert all(row["_networkInstance"] in (None, NETWORK) for row in rows)
    assert any(row["_networkInstance"] is None for row in rows)


@pytest.mark.parametrize("change,reason", [
    ({"nodeCount": 99}, "outcome-count-mismatch:"),
    ({"startedAt": "2026-02-01T00:00:00+00:00"}, "unbound-outcome-capture:"),
    ({"completedAt": "2025-12-31T00:00:00+00:00"}, "unbound-outcome-capture:"),
])
def test_ha_outcome_counts_and_capture_times_must_match_the_original_native_snapshot(tmp_path, change, reason):
    entry = _seed_ha(tmp_path)
    filename = "td-ha-matter-ws-network-topology.outcome.json"
    payload = json.loads((tmp_path / filename).read_text())
    _save(tmp_path, filename, {**payload, **change})
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["materializationState"] == "complete"
    assert result["healthState"] == "degraded"
    assert reason + filename in result["coverage"]["healthReasons"]


def test_ha_dangling_links_are_reported_and_do_not_connect_to_another_device(tmp_path):
    entry = _seed_ha(tmp_path)
    filename = "td-ha-matter-ws-network-topology.json"
    payload = json.loads((tmp_path / filename).read_text())
    payload["topology"]["connections"][0]["target"] = "absent"
    _save(tmp_path, filename, payload)
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    assert result["rowCount"] == 3 and result["healthState"] == "degraded"
    [link] = result["coverage"]["unresolvedNativeRelationships"]
    assert link["unresolvedEndpoints"] == ["absent"]
    assert link["targetId"] == "ha-native:absent"
    assert "unresolved-native-relationships" in result["coverage"]["healthReasons"]


def test_ha_shared_thread_address_never_collapses_different_matter_fabrics(tmp_path):
    entry = _seed_ha(tmp_path)
    filename = "td-ha-matter-ws-devices-fetch-all.json"
    devices = json.loads((tmp_path / filename).read_text())
    other = copy.deepcopy(devices[0])
    other["matter"]["matterId"] = "2222333344445555-0000000000000001"
    other["matter"]["compressedFabricId"] = "2222333344445555"
    _save(tmp_path, filename, [*devices, other])
    result = unified.build_unified_dataset(tmp_path, entry["value"])
    rows = json.loads((tmp_path / entry["files"][0]).read_text())
    fabrics = {row["matter"]["matterId"] for row in rows if isinstance(row.get("matter"), dict)}
    assert other["matter"]["matterId"] in fabrics
    assert devices[0]["matter"]["matterId"] in fabrics
    assert result["coverage"]["commissionedInventory"]["selectedRecordCount"] == 3
    assert result["healthState"] == "degraded"
    assert "ambiguous-native-or-merged-identity" in result["coverage"]["healthReasons"]
    by_id = {row["_unifiedRecordId"]: row for row in rows}
    for row in rows:
        for link in row.get("nativeRelationships", []):
            assert link["sourceId"] in by_id and link["targetId"] in by_id


def test_ha_excluded_products_are_never_read_and_malformed_optional_rows_retain_prior_generation(tmp_path, monkeypatch):
    entry = _seed_ha(tmp_path)
    excluded = {"td-ha-matter-ws-thread-diagnostics.json", "td-ha-matter-ws-server-info.json"}
    for filename in excluded:
        (tmp_path / filename).write_bytes(b"not JSON, networkKey forbidden")
    original = Path.open
    def checked_open(path, *args, **kwargs):
        assert path.name not in excluded
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", checked_open)
    unified.build_unified_dataset(tmp_path, entry["value"])
    assert set(unified.read_generation(tmp_path, entry)["excluded"]) == excluded
    before = _artifacts(tmp_path, entry)
    _save(tmp_path, "td-ha-matter-ws-diagnostics-fetch-all.json",
          [{"extAddress": "0011223344556677", "nativeRelationships": "invalid"}])
    with pytest.raises(unified.UnifiedDatasetError, match="native relationships"):
        unified.build_unified_dataset(tmp_path, entry["value"], allow_partial=True)
    assert before == _artifacts(tmp_path, entry)


@pytest.mark.parametrize("payload", [{}, [None], [{}], [{"matter": {}}],
                                     [{"matter": {"matterId": ""}}]])
def test_ha_inventory_rejects_malformed_members_instead_of_dropping_them(payload):
    with pytest.raises(MatterWsContractError, match="commissioned Matter"):
        normalize_inventory(payload)


def test_ha_inventory_unknown_and_contradictory_thread_context_are_distinct():
    inventory = [{"matter": {"matterId": "1111222233334444-0000000000000001", "nodeId": 1},
                  "thread": {"extendedPanId": None}, "extPanId": None}]
    [row] = normalize_inventory(inventory)
    assert row["extPanId"] is None and row["thread"]["extendedPanId"] is None
    assert "isRouter" not in row
    inventory[0]["extPanId"] = NETWORK[7:]
    inventory[0]["thread"]["extendedPanId"] = OTHER_NETWORK[7:]
    with pytest.raises(MatterWsContractError, match="contradicts"):
        normalize_inventory(inventory)


def test_ha_inventory_canonical_values_and_mixed_node_id_types_are_not_rebuilt_or_reordered():
    inventory = [
        {"matter": {"matterId": "1111222233334444-ffffffffffffffff",
                    "nodeId": "18446744073709551615"},
         "deviceLabel": "cached label", "available": False, "vendorName": None,
         "powerSources": [{"endpointId": 2, "batteryPercent": 0}],
         "_merge_conflicts": [{"path": "deviceLabel", "current": "cached label", "incoming": "older"}]},
        {"matter": {"matterId": "1111222233334444-0000000000000001", "nodeId": 1}},
    ]
    rows = normalize_inventory(inventory)
    assert [row["matter"]["nodeId"] for row in rows] == ["18446744073709551615", 1]
    for field in ("deviceLabel", "available", "vendorName", "powerSources", "_merge_conflicts"):
        assert rows[0][field] == inventory[0][field]


def test_ha_border_router_maps_only_ipv6_and_retains_native_details_and_explicit_roles():
    native = _ha_native_fixture()["borderRouters"]
    native[0]["br"] = False
    payload = _ha_wrapper("borderRouters", native)
    before = copy.deepcopy(payload)
    [row] = normalize_border_routers(payload)
    assert payload == before
    assert row["extAddress"] == "aabbccddeeff0011"
    assert row["extPanId"] == "1122334455667788"
    assert row["vendorModel"] == "Example Border Router"
    assert row["vendorSwVersion"] == "1.2.3"
    assert row["ipv6Addresses"] == ["2001:db8::10"]
    assert row["isBorderRouter"] is False
    assert row["isRouter"] is True
    assert "isLeader" not in row
    assert "hostname" not in row
    assert row["diagnosticsDetail"]["nativeBorderRouter"]["meshcopPort"] == 49191
    assert row["diagnosticsDetail"]["nativeBorderRouter"]["addresses"] == ["192.0.2.10", "2001:db8::10"]
    assert row["_merge_conflicts"] == [
        {"path": "isBorderRouter", "current": False, "incoming": True},
    ]
    assert "not-published" not in json.dumps(row)


def test_ha_native_topology_separates_native_ids_and_qualitative_directional_evidence():
    payload = _ha_wrapper("topology", _ha_native_fixture()["topology"])
    before = copy.deepcopy(payload)
    rows = normalize_native_topology(payload)
    assert payload == before
    assert rows == normalize_native_topology(payload)
    device, border, access_point = rows
    assert device["rloc16"] == "0x0400"
    assert device["extPanId"] == "1122334455667788"
    assert device["nativeNodeIds"] == ["1"]
    assert "matterId" not in device and "nodeId" not in device and "matter" not in device
    assert device["diagnosticsDetail"]["nativeTopology"]["node"]["node_id"] == "18446744073709551615"
    assert access_point["id"] == "ha-native:ap_112233445566"
    assert access_point["type"] == "nativeDevice"
    assert "role" not in access_point and "isRouter" not in access_point
    assert access_point["diagnosticsDetail"]["nativeTopology"]["node"]["ssid"] == "Test WiFi"
    thread_link, wifi_link = device["nativeRelationships"]
    assert thread_link["sourceId"] == device["topologyId"]
    assert thread_link["targetId"] == border["topologyId"]
    assert thread_link["sourceToTarget"] == {"strength": "medium", "lqi": 2, "rssi": -70}
    assert thread_link["targetToSource"] == {"strength": "unknown"}
    assert thread_link["strength"] == "unknown"
    assert thread_link["viaRouteTable"] is True and thread_link["pathCost"] == 1
    assert wifi_link["networkType"] == "wifi" and wifi_link["targetId"] == access_point["topologyId"]
    assert "targetToSource" not in wifi_link and "lqi" not in wifi_link["sourceToTarget"]
    assert all(not any(field in row for field in ("routerNeighbors", "children", "route"))
               for row in rows)


@pytest.mark.parametrize("endpoints", [
    {"target": "missing"}, {"source": "missing"}, {"source": "missing", "target": "also-missing"},
])
def test_ha_native_dangling_links_are_inspectable_but_live_validator_remains_strict(endpoints):
    graph = _ha_native_fixture()["topology"]
    graph["connections"] = [{**graph["connections"][0], **endpoints}]
    with pytest.raises(MatterWsContractError, match="existing node id"):
        validate_native_topology(graph)
    rows = normalize_native_topology(_ha_wrapper("topology", graph))
    owner = next(row for row in rows if row["nativeRelationships"])
    [link] = owner["nativeRelationships"]
    assert set(link["unresolvedEndpoints"]) == set(endpoints.values())
    assert owner["_merge_conflicts"][0]["path"] == "nativeRelationships.unresolvedEndpoints"
    if "source" in endpoints and "target" in endpoints:
        assert owner["relationshipOnly"] is True
        assert owner["type"] == "nativeRelationship"


def test_ha_native_duplicate_observations_and_identity_collisions_are_not_arbitrarily_connected():
    graph = _ha_native_fixture()["topology"]
    graph["connections"].append(copy.deepcopy(graph["connections"][0]))
    graph["nodes"].append({**graph["nodes"][0], "id": "alias"})
    rows = normalize_native_topology(_ha_wrapper("topology", graph))
    first, alias = rows[0], rows[-1]
    assert first["topologyId"] == "ha-native:1"
    assert alias["topologyId"] == "ha-native:alias"
    assert first["_merge_conflicts"][0]["path"] == "nativeNodeIds.ambiguousIdentity"
    assert len(first["nativeRelationships"]) == 2
    assert first["nativeRelationships"][0]["sourceId"] == "ha-native:1"


def test_ha_native_reuses_cached_role_conflicts_without_relaxing_native_validation():
    graph = _ha_native_fixture()["topology"]
    graph["nodes"][0].update(
        isRouter=True, role="reed",
        _merge_conflicts=[{"path": "isRouter", "current": True, "incoming": False}],
    )
    [device, *_] = normalize_native_topology(_ha_wrapper("topology", graph))
    assert device["isRouter"] is True and device["isReed"] is True
    assert device["_merge_conflicts"] == graph["nodes"][0]["_merge_conflicts"]
    graph["nodes"][0]["_merge_conflicts"] = [{"path": "networkKey", "current": False, "incoming": True}]
    with pytest.raises(MatterWsContractError, match="native role conflicts"):
        normalize_native_topology(_ha_wrapper("topology", graph))


@pytest.mark.parametrize("extractor,field", [
    ("ha-border-routers", "borderRouters"), ("ha-native-topology", "topology"),
])
def test_ha_source_converters_are_wired_to_cache_processing_with_explicit_errors(extractor, field):
    payload = _ha_wrapper(field, _ha_native_fixture()[field])
    item = {"file": "td-ha-matter-ws-test.json", "extractor": extractor}
    rows = unified._extract(item, payload)
    assert rows
    payload["schemaVersion"] = "future"
    with pytest.raises(unified.UnifiedDatasetError, match="Invalid cached HA product"):
        unified._extract(item, payload)


def test_ha_native_empty_products_and_secret_rejection():
    assert normalize_border_routers(_ha_wrapper("borderRouters", [])) == []
    assert normalize_native_topology(_ha_wrapper(
        "topology", {"collected_at": 0, "nodes": [], "connections": []},
    )) == []
    assert normalize_inventory([]) == []
    payload = _ha_wrapper("topology", _ha_native_fixture()["topology"])
    payload["topology"]["nodes"][0]["networkKey"] = "forbidden"
    with pytest.raises(MatterSnapshotSecurityError):
        normalize_native_topology(payload)


def test_ha_unified_converter_has_no_live_client_imports():
    result = subprocess.run([
        sys.executable, "-c",
        "import sys; import ha_matter_ws_unified; "
        "assert not {'ha_matter_ws_cli', 'ha_matter_ws_client', 'ha_matter_ws_fetch_all'} & sys.modules.keys()",
    ], capture_output=True, text=True, cwd=ROOT / "src", timeout=30)
    assert result.returncode == 0, result.stderr


def _run_fetch_script_stub(
    tmp_path, script_name, *, fail_dataset="", fail_guard=False, stage_only=False,
):
    repo = tmp_path / "fetch-repo"
    scripts = repo / "script"
    scripts.mkdir(parents=True)
    (repo / "src").mkdir()
    data = repo / "data"
    data.mkdir()
    (data / "td-merged-topology-all.json").write_text("[]")
    script = scripts / script_name
    shutil.copyfile(ROOT / "script" / script_name, script)
    if stage_only:
        stage = script.read_text().split("# Unified materialization uses cached snapshots only.\n", 1)[1]
        stage = stage.split("#mdns scope", 1)[0].split("# process health", 1)[0]
        script.write_text(stage + '\nexit "$unified_status"\n')
    (scripts / "py-activate.sh").write_text(":\n")
    binaries = repo / "bin"
    binaries.mkdir()
    calls = repo / "calls.jsonl"
    python_stub = binaries / "python3"
    python_stub.write_text(f"#!{sys.executable}\n" + """
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FETCH_TEST_CALLS"], "a") as stream:
    stream.write(json.dumps({"args": args, "data": os.environ["TD_DATA_DIR"]}) + "\\n")
if args[0] == "-c":
    sys.exit(7 if os.environ["FETCH_TEST_GUARD"] == "fail" else 0)
if "unify-dataset" in args:
    dataset = args[args.index("--dataset") + 1]
    if dataset == os.environ["FETCH_TEST_FAIL"]:
        sys.exit(9)
    print(json.dumps({"datasetId": dataset, "materializationState": "partial"}))
""")
    python_stub.chmod(0o755)
    for name in ("jq", "column"):
        binary = binaries / name
        binary.write_text("#!/bin/sh\ncat\n")
        binary.chmod(0o755)
    external_data = repo / "cached data"
    external_data.mkdir()
    environment = {
        **os.environ,
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "TD_DATA_DIR": str(external_data),
        "FETCH_TEST_CALLS": str(calls),
        "FETCH_TEST_GUARD": "fail" if fail_guard else "success",
        "FETCH_TEST_FAIL": fail_dataset,
        "TD_EXT_PAN_ID": NETWORK[7:],
    }
    result = subprocess.run(
        ["bash", str(script)], cwd=repo, env=environment,
        capture_output=True, text=True, timeout=30,
    )
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    return result, commands, repo


@pytest.mark.parametrize("script_name", ["td-fetch.sh", "td-fetch-quick.sh"])
@pytest.mark.parametrize("fail_guard", [False, True])
def test_fetch_scripts_build_five_cache_only_products_before_health(tmp_path, script_name, fail_guard):
    result, commands, repo = _run_fetch_script_stub(tmp_path, script_name, fail_guard=fail_guard)
    assert result.returncode == 0, result.stderr
    arguments = [command["args"] for command in commands]
    stage = [args for args in arguments if "unify-dataset" in args]
    datasets = [args[args.index("--dataset") + 1] for args in stage]
    assert datasets == [*DATASET_IDS, "multi_source_unified"]
    expected_data = repo / "data"
    assert '--datadir "$TD_DATA_DIR" unify-dataset' in (ROOT / "script" / script_name).read_text()
    assert all(command["data"] == str(expected_data) for command in commands)
    for args, dataset in zip(stage, datasets, strict=True):
        assert args[:5] == ["-m", "td_cli", "--datadir", str(expected_data), "unify-dataset"]
        assert args[-2:] == ["--allow-partial", "--json"]
        if dataset == "mdns_unified":
            assert "--network" not in args
        else:
            assert args[args.index("--network") + 1] == "extpan:78b9775b001c1cbe"
    merge = arguments.index(["-m", "td_cli", "merge-dataset"])
    health = ["-m", "td_cli", "health", "process-dataset", "--dataset", "all", "--allow-partial"]
    assert arguments[merge + 1:] == [*stage, health]
    assert arguments.index(["-m", "td_cli", "process-eve"]) < merge
    assert result.stdout.count('"materializationState": "partial"') == 5
    assert "Time taken:" in result.stdout
    assert ["-m", "td_cli", "ha-matter-ws", "devices", "fetch-all"] in arguments
    rest_fetches = [args for args in arguments if args[:4] == ["-m", "td_cli", "otbr-restapi", "devices"]]
    assert bool(rest_fetches) is not fail_guard
    if fail_guard:
        assert "skipping REST collection and continuing with HA Matter" in result.stderr
    if script_name == "td-fetch-quick.sh":
        assert ["-m", "td_cli", "otbr-cli", "networkdiag", "fetch-all", "-cno"] in arguments
        assert not any(args[2:4] == ["otbr-cli", "meshdiag"] for args in arguments)
        assert not any(args[2:5] in (
            ["otbr-restapi", "diagnostics", "fetch-all"],
            ["otbr-restapi", "mesh-diagnostics", "fetch-all"],
        ) for args in arguments)
    else:
        assert len(list((repo / "data").glob("td-jq-*.txt"))) == 2
        if not fail_guard:
            assert ["-m", "td_cli", "otbr-restapi", "diagnostics", "fetch-all",
                    "--items-only", "--no-update-devices", "--no-basic-fallback"] in arguments
            assert ["-m", "td_cli", "otbr-restapi", "mesh-diagnostics", "fetch-all",
                    "--routers-only", "--items-only", "--no-update-devices",
                    "--preserve-diagnostics", "--no-fallback"] in arguments


@pytest.mark.parametrize("script_name", ["td-fetch.sh", "td-fetch-quick.sh"])
@pytest.mark.parametrize("fail_dataset", [*DATASET_IDS, "multi_source_unified"])
def test_fetch_scripts_gate_composition_and_health_on_new_stage_failures(
    tmp_path, script_name, fail_dataset,
):
    result, commands, repo = _run_fetch_script_stub(
        tmp_path, script_name, fail_dataset=fail_dataset,
    )
    assert result.returncode != 0
    stage = [command["args"] for command in commands if "unify-dataset" in command["args"]]
    datasets = [args[args.index("--dataset") + 1] for args in stage]
    assert datasets[:4] == list(DATASET_IDS)
    assert ("multi_source_unified" in datasets) is (fail_dataset == "multi_source_unified")
    assert not any("health" in command["args"] for command in commands)
    assert f"Unified build failed: {fail_dataset} (exit 9)." in result.stderr
    assert "Skipping health processing" in result.stderr
    assert "Time taken:" in result.stdout
    if script_name == "td-fetch.sh":
        assert len(list((repo / "data").glob("td-jq-*.txt"))) == 2


@pytest.mark.parametrize("script_name", ["td-fetch.sh", "td-fetch-quick.sh"])
def test_fetch_script_new_stage_preserves_quoted_effective_datadir(tmp_path, script_name):
    result, commands, repo = _run_fetch_script_stub(tmp_path, script_name, stage_only=True)
    assert result.returncode == 0, result.stderr
    assert len(commands) == 5
    for command in commands:
        args = command["args"]
        assert args[2:5] == ["--datadir", str(repo / "cached data"), "unify-dataset"]
        assert command["data"] == str(repo / "cached data")
