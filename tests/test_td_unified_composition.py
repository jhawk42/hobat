"""Cache-only four-primary composition; no collectors or production cache."""

import asyncio
import copy
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web

import merge_dataset
import td_unified_dataset as unified
import td_webserver
from td_dataset_catalog import load_dataset_catalog, resolve_dataset, validate_dataset_catalog
from td_health_manifest import HealthManifestError
from td_source_capabilities import SourceCapabilityService
from test_td_unified_dataset import (
    DATASET_IDS, NETWORK, OTHER_NETWORK, _artifacts, _entry, _save, _seed,
)


TARGET = "multi_source_unified"


def _seed_all(directory):
    for dataset_id in DATASET_IDS:
        _seed(directory, dataset_id)
    return _entry(TARGET)


def _rows(directory, entry):
    return json.loads((directory / entry["files"][0]).read_text())


def test_complete_raw_authority_closure_and_no_op(tmp_path):
    entry = _seed_all(tmp_path)
    with patch.object(unified, "_build_locked", wraps=unified._build_locked) as builder:
        result = unified.build_unified_dataset(tmp_path, TARGET)
    assert [call.args[1]["value"] for call in builder.call_args_list] == [TARGET, *DATASET_IDS]
    assert result["materializationState"] == "complete"
    report = unified.read_generation(tmp_path, entry, verify_inputs=True)
    assert len(report["coverage"]["sources"]) == 4
    assert all(state["status"] == "complete" for state in report["coverage"]["sources"].values())
    raw_files = {item["filename"] for item in report["rawInputs"]}
    assert raw_files == {
        item["file"] for dataset_id in DATASET_IDS for item in _entry(dataset_id)["unified"]["inputs"]
    }
    for lineage in report["recordSources"].values():
        assert all(origin["filename"] in raw_files for origin in lineage)
    for lineage in report["fieldSources"].values():
        assert all(origin["filename"] in raw_files for origins in lineage.values() for origin in origins)
    rows = _rows(tmp_path, entry)
    assert any(row.get("type") == "service" for row in rows)
    artifacts = _artifacts(tmp_path, entry)
    dependencies = {dataset_id: _artifacts(tmp_path, _entry(dataset_id)) for dataset_id in DATASET_IDS}
    repeat = unified.build_unified_dataset(tmp_path, TARGET)
    assert repeat["noOp"] is True
    assert _artifacts(tmp_path, entry) == artifacts
    assert dependencies == {dataset_id: _artifacts(tmp_path, _entry(dataset_id)) for dataset_id in DATASET_IDS}


def test_explicit_partial_missing_sources_and_zero_usable(tmp_path):
    entry = _seed(tmp_path, "mdns_unified")
    target = _entry(TARGET)
    with pytest.raises(unified.UnifiedDatasetError, match="Missing required"):
        unified.build_unified_dataset(tmp_path, TARGET)
    result = unified.build_unified_dataset(tmp_path, TARGET, allow_partial=True)
    assert result["materializationState"] == "partial"
    assert result["healthState"] == "unavailable"
    assert result["coverage"]["sources"]["mdns"]["status"] == "complete"
    assert all(row["type"] == "service" for row in _rows(tmp_path, target))
    for item in entry["unified"]["inputs"]:
        (tmp_path / item["file"]).unlink()
    before = _artifacts(tmp_path, target)
    with pytest.raises(unified.UnifiedDatasetError, match="No usable"):
        unified.build_unified_dataset(tmp_path, TARGET, allow_partial=True)
    assert _artifacts(tmp_path, target) == before


def test_source_partial_propagates(tmp_path):
    _seed_all(tmp_path)
    recipe = _entry("otbr_cli_unified")["unified"]
    (tmp_path / recipe["inputs"][0]["file"]).unlink()
    result = unified.build_unified_dataset(tmp_path, TARGET, allow_partial=True)
    assert result["materializationState"] == "partial"
    assert result["coverage"]["sources"]["otbr-cli"]["status"] == "partial"


def test_malformed_optional_aborts_and_preserves_previous(tmp_path):
    entry = _seed_all(tmp_path)
    unified.build_unified_dataset(tmp_path, TARGET)
    before = _artifacts(tmp_path, entry)
    optional = next(item for item in _entry("otbr_cli_unified")["unified"]["inputs"]
                    if not item["required"] and item["role"] == "records")
    (tmp_path / optional["file"]).write_text("{")
    with pytest.raises(unified.UnifiedDatasetError, match="Invalid cached JSON"):
        unified.build_unified_dataset(tmp_path, TARGET, allow_partial=True)
    assert _artifacts(tmp_path, entry) == before


def test_stale_transitive_inputs_do_not_break_display_but_reject_evidence(tmp_path):
    entry = _seed_all(tmp_path)
    unified.build_unified_dataset(tmp_path, TARGET)
    raw = _entry("otbr_cli_unified")["unified"]["inputs"][0]["file"]
    _save(tmp_path, raw, [{"extAddress": "0011223344556677", "deviceLabel": "changed"}])
    assert unified.read_generation(tmp_path, entry)["materializationState"] == "complete"
    with pytest.raises(unified.UnifiedDatasetError, match="Stale"):
        unified.read_generation(tmp_path, entry, verify_inputs=True)
    assert unified.build_unified_dataset(tmp_path, TARGET)["noOp"] is False


def test_touching_aggregate_files_does_not_create_new_observation(tmp_path):
    entry = _seed_all(tmp_path)
    result = unified.build_unified_dataset(tmp_path, TARGET)
    before = _artifacts(tmp_path, entry)
    for dataset_id in DATASET_IDS:
        os.utime(tmp_path / _entry(dataset_id)["files"][0], None)
    repeat = unified.build_unified_dataset(tmp_path, TARGET)
    assert repeat["generationId"] == result["generationId"]
    assert repeat["noOp"] is True
    assert _artifacts(tmp_path, entry) == before


def test_network_selection_excludes_mismatched_source_without_relabelling_unknown(tmp_path):
    entry = _seed_all(tmp_path)
    rest = _entry("otbr_restapi_unified")
    for item in rest["unified"]["inputs"]:
        path = tmp_path / item["file"]
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        if item["role"] == "identity":
            payload["extPanId"] = OTHER_NETWORK[7:]
        _save(tmp_path, item["file"], payload, scope=OTHER_NETWORK)
    result = unified.build_unified_dataset(tmp_path, TARGET, network=NETWORK, allow_partial=True)
    assert result["materializationState"] == "partial"
    assert result["coverage"]["sources"]["otbr-restapi"]["status"] == "excluded"
    assert all(row["_networkInstance"] in {None, NETWORK} for row in _rows(tmp_path, entry))
    assert all(row["_networkInstance"] is None for row in _rows(tmp_path, entry)
               if row.get("type") == "service" and row.get("extPanId") is None)


def test_catalog_requires_exact_four_primary_closure_and_legacy_full_unchanged():
    catalog = load_dataset_catalog()
    assert catalog["mergeGroups"]["unified"]["files"] == [
        {"file": item["file"], "order": index + 1}
        for index, item in enumerate(resolve_dataset(catalog, TARGET)["unified"]["inputs"])
    ]
    assert catalog["mergeGroups"]["full"]["composedOf"] == [
        "otbr-cli", "otbr-restapi", "ha-matter-ws", "mdns",
    ]
    target = resolve_dataset(catalog, TARGET)
    assert target["selectable"] is True and target["healthEligible"] is True
    malformed = copy.deepcopy(catalog)
    resolve_dataset(malformed, TARGET)["unified"]["inputs"].pop()
    with pytest.raises(HealthManifestError, match="exactly four"):
        validate_dataset_catalog(malformed)


def test_capabilities_derive_raw_dependency_buildability_without_writes(tmp_path):
    _seed(tmp_path, "mdns_unified")
    before = sorted(path.name for path in tmp_path.iterdir())
    info = unified.inspect_unified_cache(tmp_path, _entry(TARGET))
    assert info["cached"] is False and info["buildableFromCache"] is True
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    raw = _entry("otbr_cli_unified")["unified"]["inputs"][0]["file"]
    (tmp_path / raw).write_text("{")
    assert unified.inspect_unified_cache(tmp_path, _entry(TARGET))["buildableFromCache"] is False


@pytest.mark.parametrize("dataset_id", ["ha_matter_ws_unified", TARGET])
@pytest.mark.parametrize("outcome_status", [None, "partial", "invalid"])
def test_capabilities_validate_ha_outcomes_in_their_own_format(tmp_path, dataset_id, outcome_status):
    _seed_all(tmp_path)
    if outcome_status is not None:
        filename = "td-ha-matter-ws-collection.outcome.json"
        outcome = json.loads((tmp_path / filename).read_text())
        _save(tmp_path, filename, {**outcome, "status": outcome_status})
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    capabilities = asyncio.run(SourceCapabilityService(probes={}).capabilities(tmp_path))
    state = capabilities["files"][_entry(dataset_id)["files"][0]]
    assert state["cached"] is False
    assert state["buildableFromCache"] is (outcome_status != "invalid")
    assert state["cacheInputState"] == ("invalid" if outcome_status == "invalid" else "usable")
    assert any("Invalid cached HA outcome" in reason for reason in state["cacheReasons"]) is (
        outcome_status == "invalid"
    )
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    if state["buildableFromCache"]:
        unified.build_unified_dataset(tmp_path, dataset_id, allow_partial=True)


def test_native_links_rebind_to_final_ids_and_non_thread_fields_survive(tmp_path):
    entry = _seed_all(tmp_path)
    unified.build_unified_dataset(tmp_path, TARGET)
    rows = _rows(tmp_path, entry)
    thread = next(row for row in rows if "native-router" in row.get("nativeNodeIds", []))
    access_point = next(row for row in rows if row.get("nativeNodeIds") == ["ap"])
    non_thread = next(row for row in rows if row.get("type") == "matterDevice")
    assert access_point["_networkInstance"] is None and non_thread["_networkInstance"] is None
    assert "isRouter" not in non_thread and "isRouter" not in access_point
    assert thread["powerSources"] == [{"endpointId": 0, "batteryPercent": 0}]
    assert thread["endpoints"] == [{"endpointId": 0, "bridged": False}]
    [link] = thread["nativeRelationships"]
    assert link["sourceId"] == thread["_unifiedRecordId"]
    assert link["targetId"] == access_point["_unifiedRecordId"]
    assert link["strength"] == "strong"
    assert "lqi" not in link and "sourceToTarget" not in link
    fields = unified.read_generation(tmp_path, entry)["fieldSources"][thread["_unifiedRecordId"]]
    assert any(path.startswith("nativeRelationships[") and path.endswith(".strength")
               for path in fields)


def test_native_thread_link_does_not_bind_different_known_networks():
    from ha_matter_ws_unified import bind_native_relationships
    rows = [
        {"_unifiedRecordId": "source", "_networkInstance": NETWORK, "nativeNodeIds": ["native-a"],
         "nativeRelationships": [{
             "sourceId": "old-source", "targetId": "old-target", "networkType": "thread",
             "nativeSourceId": "native-a", "nativeTargetId": "native-b",
         }]},
        {"_unifiedRecordId": "target", "_networkInstance": OTHER_NETWORK, "nativeNodeIds": ["native-b"]},
    ]
    bound, unresolved = bind_native_relationships(rows)
    assert bound[0]["nativeRelationships"][0]["sourceId"] == "source"
    assert bound[0]["nativeRelationships"][0]["targetId"] == "ha-native:native-b"
    assert unresolved[0]["unresolvedEndpoints"] == ["native-b"]
    assert any(conflict["path"] == "nativeRelationships.networkMismatch"
               for conflict in bound[0]["_merge_conflicts"])


def test_meshcop_scope_does_not_spread_to_other_services(tmp_path):
    entry = _seed_all(tmp_path)
    mdns = _entry("mdns_unified")
    for item in mdns["unified"]["inputs"]:
        _save(tmp_path, item["file"], [
            {"scope": "_meshcop._udp.local.", "name": "br",
             "serviceInfo": {"name": "br", "properties": {"xp": {"hex": NETWORK[7:]}}}},
            {"scope": "_hap._tcp.local.", "name": "unscoped-hap",
             "serviceInfo": {"name": "unscoped-hap"}},
        ])
    unified.build_unified_dataset(tmp_path, TARGET)
    rows = _rows(tmp_path, entry)
    assert next(row for row in rows if row.get("name") == "br")["_networkInstance"] == NETWORK
    assert next(row for row in rows if row.get("name") == "unscoped-hap")["_networkInstance"] is None


def test_source_with_only_mismatched_services_is_excluded_not_complete(tmp_path):
    _seed_all(tmp_path)
    for item in _entry("mdns_unified")["unified"]["inputs"]:
        _save(tmp_path, item["file"], [{
            "scope": "_meshcop._udp.local.", "name": "other-br",
            "serviceInfo": {"name": "other-br", "properties": {"xp": {"hex": OTHER_NETWORK[7:]}}},
        }], scope=OTHER_NETWORK)
    summary = unified.build_unified_dataset(tmp_path, TARGET, network=NETWORK, allow_partial=True)
    assert summary["materializationState"] == "partial"
    assert summary["coverage"]["sources"]["mdns"]["status"] == "excluded"
    assert not any(row.get("name") == "other-br" for row in _rows(tmp_path, _entry(TARGET)))


def test_fabrics_sharing_thread_address_do_not_collapse(tmp_path):
    entry = _seed_all(tmp_path)
    filename = "td-ha-matter-ws-devices-fetch-all.json"
    inventory = json.loads((tmp_path / filename).read_text())
    other = copy.deepcopy(inventory[0])
    other["matter"]["matterId"] = "9999222233334444-0000000000000001"
    inventory.append(other)
    _save(tmp_path, filename, inventory)
    unified.build_unified_dataset(tmp_path, TARGET)
    identities = [row.get("matter", {}).get("matterId") for row in _rows(tmp_path, entry)]
    assert "1111222233334444-0000000000000001" in identities
    assert "9999222233334444-0000000000000001" in identities


OMR = "fd6b:32e0:d18:0:32a2:337b:1b57:fb41"


def _matter_service(fabric, node="0000000000000001", address=OMR):
    name = f"{fabric}-{node}._matter._tcp.local."
    return {
        "scope": "_matter._tcp.local.", "name": name, "omrIpv6Address": address,
        "capturedAtEpoch": 1_767_225_600,
        "serviceInfo": {
            "name": name, "key": name.lower(), "server": "device.local.", "port": 5540,
            "properties": {
                "fabricIdCompressed": {"decoded": fabric},
                "nodeId": {"decoded": node},
            },
        },
    }


def _hap_service(address=OMR):
    name = "Encode Plus 1._hap._udp.local."
    return {
        "scope": "_hap._udp.local.", "name": name, "omrIpv6Address": address,
        "capturedAtEpoch": 1_767_225_600,
        "serviceInfo": {
            "name": name, "key": name.lower(), "server": "lock.local.", "port": 5683,
            "properties": {"id": {"decoded": "AA:BB:CC:DD:EE:FF"}},
        },
    }


@pytest.mark.parametrize("device_first", [False, True])
def test_real_device_contribution_clears_relationship_only_marker(device_first):
    placeholder = {
        "extAddress": "0011223344556677", "omrIpv6Address": OMR,
        "relationshipOnly": True, "role": "unknown",
    }
    device = {"extAddress": placeholder["extAddress"], "role": "router"}
    sources = [("relationships.json", [placeholder]), ("observations.json", [device])]
    if device_first:
        sources.reverse()
    before = copy.deepcopy(sources)
    rows, contributors = merge_dataset.merge_cached_records(sources, None)
    assert len(rows) == 1
    assert rows[0]["relationshipOnly"] is False
    assert len(contributors[0]) == 2
    assert sources == before
    assert any(original.get("relationshipOnly") is True for _, original in contributors[0])


@pytest.mark.parametrize("enrichment", ["placeholder", "mdns"])
def test_relationship_only_marker_survives_without_device_observation(enrichment):
    placeholder = {
        "extAddress": "0011223344556677", "omrIpv6Address": OMR,
        "relationshipOnly": True,
    }
    other = copy.deepcopy(placeholder) if enrichment == "placeholder" else _hap_service()
    rows, _ = merge_dataset.merge_cached_records([
        ("relationships.json", [placeholder]), ("enrichment.json", [other]),
    ], None)
    assert len(rows) == 1
    assert rows[0]["relationshipOnly"] is True


def test_mixed_mdns_records_embed_after_real_observation_resolves_placeholder():
    address = "fd6b:32e0:d18:0:1f10:486f:979b:8c30"
    services = [_hap_service(address), _matter_service("1111222233334444", address=address)]
    rows, record_sources, field_sources = unified._assemble([
        (NETWORK[7:], "td-ha-matter-ws-topology.json", [{
            "extAddress": "ba94dd47637d782b", "relationshipOnly": True,
        }]),
        (NETWORK[7:], "td-otbr-cli-networkdiag-fetch-all.json", [{
            "extAddress": "ba94dd47637d782b", "omrIpv6Address": address, "role": "router",
        }]),
        (None, "td-mdns-scopes-thread.json", services),
    ])
    assert len(rows) == 1
    [device] = rows
    assert device["relationshipOnly"] is False
    assert {record["name"] for record in device["mdnsRecords"]} == {s["name"] for s in services}
    for service in device["mdnsRecords"]:
        original = next(s for s in services if s["name"] == service["name"])
        assert all(service[key] == value for key, value in original.items())
        assert service["_networkInstance"] is None
        assert service["_source_files"] == ["td-mdns-scopes-thread.json"]
    device_id = device["_unifiedRecordId"]
    assert len(record_sources[device_id]) == 4
    assert set(record_sources) == set(field_sources) == {device_id}
    hap_origins = [
        origins for path, origins in field_sources[device_id].items()
        if path.startswith("mdnsRecords[") and path.endswith("properties.id.decoded")
    ]
    assert len(hap_origins) == 1
    assert hap_origins[0][0]["filename"] == "td-mdns-scopes-thread.json"
    assert "matter" not in device and "serviceInfo" not in device


@pytest.mark.parametrize("include_hap", [False, True])
def test_matter_services_embed_in_matching_thread_row_with_original_lineage(tmp_path, include_hap):
    entry = _seed_all(tmp_path)
    cli_file = "td-otbr-cli-networkdiag-fetch-all.json"
    _save(tmp_path, cli_file, [{
        "extAddress": "0011223344556677", "omrIpv6Address": OMR, "deviceLabel": "Thread",
    }])
    services = [_matter_service(fabric) for fabric in ("1111222233334444", "9999222233334444")]
    if include_hap:
        services.append(_hap_service())
    for item in _entry("mdns_unified")["unified"]["inputs"]:
        records = services[:2] if "scopes-matter" in item["file"] else (
            services[2:] if "scopes-thread" in item["file"] else []
        )
        _save(tmp_path, item["file"], records)
    result = unified.build_unified_dataset(tmp_path, TARGET)
    rows = _rows(tmp_path, entry)
    device = next(row for row in rows if row.get("extAddress") == "0011223344556677")
    assert not any(row.get("type") == "service" for row in rows)
    assert device["deviceLabel"] == "Thread"
    assert len(device["mdnsRecords"]) == len(services)
    assert {record["name"] for record in device["mdnsRecords"]} == {s["name"] for s in services}
    assert all(record["_networkInstance"] is None for record in device["mdnsRecords"])
    assert device["_networkInstance"] == NETWORK
    assert len({record["_unifiedRecordId"] for record in device["mdnsRecords"]}) == len(services)
    primary = _rows(tmp_path, _entry("mdns_unified"))
    assert device["mdnsRecords"] == primary
    assert all(row["type"] == "service" for row in primary)
    report = unified.read_generation(tmp_path, entry, verify_inputs=True)
    sources = report["recordSources"][device["_unifiedRecordId"]]
    mdns_sources = [source for source in sources if source["filename"].startswith("td-mdns-")]
    assert len({source["recordId"] for source in mdns_sources}) == len(services)
    fields = report["fieldSources"][device["_unifiedRecordId"]]
    assert fields["mdnsRecords"] == mdns_sources
    fabric_fields = {path: origins for path, origins in fields.items()
                    if path.startswith("mdnsRecords[") and path.endswith("fabricIdCompressed.decoded")}
    assert len(fabric_fields) == 2
    assert all(len(origins) == 1 and origins[0] in mdns_sources for origins in fabric_fields.values())
    assert all(origin["filename"] == cli_file for origin in fields["omrIpv6Address"])
    before = _artifacts(tmp_path, entry)
    assert unified.build_unified_dataset(tmp_path, TARGET)["noOp"] is True
    assert before == _artifacts(tmp_path, entry)
    assert result["generationId"] == report["generationId"]


@pytest.mark.parametrize("service_kind", ["matter", "hap"])
@pytest.mark.parametrize(("device_scope", "service_scope"), [
    (NETWORK[7:], None), (None, None), (NETWORK[7:], NETWORK[7:]),
])
def test_matter_service_matching_normalizes_ipv6_without_relabelling_service(
    device_scope, service_scope, service_kind,
):
    service = _matter_service("1111222233334444") if service_kind == "matter" else _hap_service()
    service["omrIpv6Address"] = "FD6B:32E0:0D18:0000:32A2:337B:1B57:FB41"
    rows, _, _ = unified._assemble([
        (device_scope, "td-otbr-cli-networkdiag-fetch-all.json", [
            {"extAddress": "0011223344556677", "omrIpv6Address": OMR},
        ]),
        (service_scope, "td-mdns-scopes-matter.json", [service]),
    ])
    assert len(rows) == 1
    assert rows[0]["mdnsRecords"][0]["_networkInstance"] == (
        f"extpan:{service_scope}" if service_scope else None
    )


@pytest.mark.parametrize("service_kind", ["matter", "hap"])
@pytest.mark.parametrize("case", [
    "no-device", "different-network", "ambiguous-network", "ambiguous-fabric",
    "non-thread", "conflicting-extaddr", "unspecified", "multicast", "link-local", "loopback",
    "not-matter", "relationship-only", "missing-address", "invalid-address",
])
def test_unmatched_or_ambiguous_matter_services_remain_standalone(case, service_kind):
    service = _matter_service("1111222233334444") if service_kind == "matter" else _hap_service()
    device = {"extAddress": "0011223344556677", "omrIpv6Address": OMR}
    device_scope, service_scope = NETWORK[7:], None
    if case == "different-network":
        service_scope = OTHER_NETWORK[7:]
    elif case == "non-thread":
        device["type"] = "matterDevice"
    elif case == "relationship-only":
        device["relationshipOnly"] = True
    elif case == "missing-address":
        service.pop("omrIpv6Address")
    elif case == "invalid-address":
        device["omrIpv6Address"] = service["omrIpv6Address"] = "invalid"
    elif case == "conflicting-extaddr":
        service["extAddress"] = "8899aabbccddeeff"
    elif case in {"unspecified", "multicast", "link-local", "loopback"}:
        address = {
            "unspecified": "::", "multicast": "ff02::1", "link-local": "fe80::1", "loopback": "::1",
        }[case]
        device["omrIpv6Address"] = service["omrIpv6Address"] = address
    elif case == "not-matter":
        service["scope"] = "_hap._tcp.local."
    sources = [(device_scope, "td-otbr-cli-networkdiag-fetch-all.json",
                [] if case == "no-device" else [device])]
    if case == "ambiguous-network":
        sources.append((OTHER_NETWORK[7:], "td-otbr-restapi-devices-fetch.json", [device]))
    elif case == "ambiguous-fabric":
        for fabric in ("1111222233334444", "9999222233334444"):
            sources.append((device_scope, "td-ha-matter-ws-devices-fetch-all.json", [{
                **device, "type": "threadDevice",
                "matter": {"matterId": fabric + "-0000000000000001"},
            }]))
    sources.append((service_scope, "td-mdns-scopes-matter.json", [service]))
    rows, _, _ = unified._assemble(sources)
    assert any(row.get("type") == "service" for row in rows)
    assert all("mdnsRecords" not in row for row in rows)


@pytest.mark.parametrize("service_kind", ["matter", "hap"])
def test_scoped_matter_service_can_choose_only_its_observed_network(service_kind):
    device = {"extAddress": "0011223344556677", "omrIpv6Address": OMR}
    service = _matter_service("1111222233334444") if service_kind == "matter" else _hap_service()
    rows, _, _ = unified._assemble([
        (NETWORK[7:], "td-otbr-cli-networkdiag-fetch-all.json", [device]),
        (OTHER_NETWORK[7:], "td-otbr-restapi-devices-fetch.json", [device]),
        (NETWORK[7:], "td-mdns-scopes-thread.json", [service]),
    ])
    assert len(rows) == 2
    assert len(next(row for row in rows if row["_networkInstance"] == NETWORK)["mdnsRecords"]) == 1
    assert "mdnsRecords" not in next(row for row in rows if row["_networkInstance"] == OTHER_NETWORK)


@pytest.mark.parametrize("service_kind", ["matter", "hap"])
def test_repeated_service_events_embed_once_with_all_contributors(service_kind):
    first = _matter_service("1111222233334444") if service_kind == "matter" else _hap_service()
    later = copy.deepcopy(first)
    later["capturedAtEpoch"] += 1
    later["serviceInfo"]["port"] = 5541
    rows, record_sources, field_sources = unified._assemble([
        (NETWORK[7:], "td-otbr-cli-networkdiag-fetch-all.json", [
            {"extAddress": "0011223344556677", "omrIpv6Address": OMR},
        ]),
        (None, "td-mdns-scopes-matter.json", [first]),
        (None, "td-mdns-scopes-thread.json", [later]),
    ])
    assert len(rows) == 1
    [service] = rows[0]["mdnsRecords"]
    assert service["serviceInfo"]["port"] == 5541
    device_id = rows[0]["_unifiedRecordId"]
    assert len(record_sources[device_id]) == 3
    port_origins = [origins for path, origins in field_sources[device_id].items()
                    if path.startswith("mdnsRecords[") and path.endswith("serviceInfo.port")]
    assert len(port_origins) == 1
    assert [origin["filename"] for origin in port_origins[0]] == ["td-mdns-scopes-thread.json"]


def test_raw_to_primary_to_composed_matches_direct_declared_raw_merge(tmp_path):
    entry = _seed_all(tmp_path)
    cli = _entry("otbr_cli_unified")
    rest = _entry("otbr_restapi_unified")
    first = cli["unified"]["inputs"][1]["file"]
    second = rest["unified"]["inputs"][0]["file"]
    _save(tmp_path, first, [{"extAddress": "0011223344556677", "deviceLabel": "CLI wins",
                              "role": "router", "sourceObservedAt": "2026-01-01T00:00:00Z"}])
    _save(tmp_path, second, {"data": [{"extAddress": "0011223344556677",
                                       "deviceLabel": "REST loses", "role": "child"}]})
    unified.build_unified_dataset(tmp_path, TARGET)
    combined = _rows(tmp_path, entry)
    thread = next(row for row in combined if "native-router" in row.get("nativeNodeIds", []))
    assert thread["deviceLabel"] == "CLI wins"
    report = unified.read_generation(tmp_path, entry)
    assert report["fieldSources"][thread["_unifiedRecordId"]]["deviceLabel"] == [{
        "filename": first,
        "recordId": report["fieldSources"][thread["_unifiedRecordId"]]["deviceLabel"][0]["recordId"],
    }]
    assert any(conflict["path"] == "deviceLabel" for conflict in thread["_merge_conflicts"])
    sources = []
    for dependency in unified._dependencies(load_dataset_catalog(), entry):
        dependency_report = unified.read_generation(tmp_path, dependency)
        metadata = {item["filename"]: item for item in dependency_report["inputs"]}
        for item in dependency["unified"]["inputs"]:
            if item["role"] not in {"records", "projection"} or metadata[item["file"]]["status"] != "selected":
                continue
            payload = json.loads((tmp_path / item["file"]).read_text())
            records = unified._extract(item, payload)
            grouped = {}
            for record in records:
                from ha_matter_ws_unified import is_thread_record
                scope = (None if dependency["source"] == "mdns"
                         or dependency["source"] == "ha-matter-ws" and not is_thread_record(record)
                         else record.get("extPanId", NETWORK[7:]))
                grouped.setdefault(scope, []).append(record)
            sources.extend((scope, item["file"], records) for scope, records in grouped.items())
    expected, _, _ = unified._assemble(sources)
    from ha_matter_ws_unified import bind_native_relationships
    expected, _ = bind_native_relationships(expected)
    assert combined == expected


@pytest.mark.parametrize("filename", unified._artifact_names(_entry(TARGET)) + [_entry(TARGET)["unified"]["reportFile"]])
def test_each_composition_publication_interruption_recovers(tmp_path, monkeypatch, filename):
    entry = _seed_all(tmp_path)
    unified.build_unified_dataset(tmp_path, TARGET)
    raw = _entry("otbr_cli_unified")["unified"]["inputs"][0]["file"]
    _save(tmp_path, raw, [{"extAddress": "0011223344556677", "testEnrichment": "new"}])
    original_replace = unified.os.replace

    def interrupt(source, destination):
        if destination.name == filename:
            raise OSError("injected composition replacement failure")
        return original_replace(source, destination)

    with monkeypatch.context() as context:
        context.setattr(unified.os, "replace", interrupt)
        with pytest.raises(OSError, match="injected"):
            unified.build_unified_dataset(tmp_path, TARGET)
    result = unified.build_unified_dataset(tmp_path, TARGET)
    assert result["materializationState"] == "complete"
    assert unified.read_generation(tmp_path, entry, verify_inputs=True)
    assert not (tmp_path / f".td-unified-{TARGET}.recovery").exists()


def test_raw_change_after_dependency_validation_preserves_prior_final(tmp_path, monkeypatch):
    entry = _seed_all(tmp_path)
    unified.build_unified_dataset(tmp_path, TARGET)
    before = _artifacts(tmp_path, entry)
    original_publish = unified._publish

    def change_before_commit(directory, target, *args):
        if target["value"] == TARGET:
            filename = _entry("otbr_cli_unified")["unified"]["inputs"][0]["file"]
            _save(directory, filename, [{"extAddress": "0011223344556677", "raced": True}])
        return original_publish(directory, target, *args)

    raw = _entry("otbr_cli_unified")["unified"]["inputs"][1]["file"]
    _save(tmp_path, raw, [{"extAddress": "0011223344556677", "changed": True}])
    monkeypatch.setattr(unified, "_publish", change_before_commit)
    with pytest.raises(unified.UnifiedDatasetError, match="changed during build"):
        unified.build_unified_dataset(tmp_path, TARGET)
    assert _artifacts(tmp_path, entry) == before


def test_complete_empty_is_distinct_from_no_usable_sources(tmp_path):
    for dataset_id in DATASET_IDS:
        _seed(tmp_path, dataset_id, empty=True)
    summary = unified.build_unified_dataset(tmp_path, TARGET)
    assert summary["materializationState"] == "complete"
    assert summary["rowCount"] == 0


def test_fifth_http_action_companions_headers_and_mixed_generation(tmp_path):
    _seed(tmp_path, "mdns_unified")
    entry = _entry(TARGET)
    unified.build_unified_dataset(tmp_path, TARGET, allow_partial=True)
    path = tmp_path / entry["files"][0]
    action = td_webserver.get_file_action(path.name)
    assert action.action == ["unify-dataset", "--dataset", TARGET, "--allow-partial", "--json"]
    assert action.force_async and action.action_cost_s * 1.5 == 60
    for filename in [*unified._artifact_names(entry)[1:], entry["unified"]["reportFile"]]:
        assert td_webserver.get_file_action(filename).action == "STATIC"
    response = td_webserver._build_file_response(path, action)
    assert response.headers["X-TD-Materialization-State"] == "partial"
    request = MagicMock(headers={"If-None-Match": response.headers["ETag"]})
    response = td_webserver._build_file_response(path, action, request)
    assert response.status == 304 and response.headers["X-TD-Materialization-State"] == "partial"
    path.write_text("[]")
    with pytest.raises(web.HTTPConflict):
        td_webserver._build_file_response(path, action, request)


def test_opt_in_merge_group_uses_safe_composer_not_aggregate_rank(tmp_path):
    _seed(tmp_path, "mdns_unified")
    assert merge_dataset.main([
        "--datadir", str(tmp_path), "--include-groups", "unified", "--allow-partial",
    ]) == 0
    assert (tmp_path / "td-merged-unified.json").exists()
    assert not (tmp_path / "td-merged-topology-all.json").exists()


def test_fifth_cli_summary_is_processing_only_and_reports_partial(tmp_path, capsys):
    _seed(tmp_path, "mdns_unified")
    assert unified.main([
        "--datadir", str(tmp_path), "--dataset", TARGET, "--allow-partial", "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["datasetId"] == TARGET and result["source"] == "multi-source"
    assert result["materializationState"] == "partial"


def test_report_rejects_reclassified_raw_roles_and_aggregate_lineage(tmp_path):
    entry = _seed_all(tmp_path)
    unified.build_unified_dataset(tmp_path, TARGET)
    marker = tmp_path / entry["unified"]["reportFile"]
    original = json.loads(marker.read_text())
    report = copy.deepcopy(original)
    next(item for item in report["rawInputs"] if item["role"] == "identity")["role"] = "records"
    marker.write_text(json.dumps(report))
    with pytest.raises(unified.UnifiedDatasetError, match="transitive Unified evidence metadata"):
        unified.read_generation(tmp_path, entry)
    report = copy.deepcopy(original)
    next(iter(report["recordSources"].values()))[0]["filename"] = entry["files"][0]
    marker.write_text(json.dumps(report))
    with pytest.raises(unified.UnifiedDatasetError, match="original-evidence Unified lineage"):
        unified.read_generation(tmp_path, entry)
