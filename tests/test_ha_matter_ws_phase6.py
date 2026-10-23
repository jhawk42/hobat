from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from merge_dataset import (
    GROUP_TO_INPUT_FILES,
    SOURCE_PRECEDENCE,
    build_merged_records,
    deep_merge,
    get_matter_fabric_node_identity,
)
from ha_matter_ws_snapshots import assert_snapshot_safe
from td_const import (
    HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
    HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    HA_MATTER_WS_SERVER_INFO_FILENAME,
    HA_MATTER_WS_TOPOLOGY_FILENAME,
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
)
from td_webserver import FILE_ACTION_MAP

pytestmark = pytest.mark.requires_data_dir


def _build(input_files, input_data):
    return build_merged_records(
        Path("."),
        "",
        input_files,
        {},
        matter_identity_mode="composite-guard",
        input_data=input_data,
    )[0]


def test_ha_matter_identity_and_merge_registration() -> None:
    record = {"matter": {"compressedFabricId": 0x1234, "nodeId": 1}}

    assert get_matter_fabric_node_identity(record) == (
        "0000000000001234|0000000000000001"
    )
    assert GROUP_TO_INPUT_FILES["ha-matter-ws"] == [HA_MATTER_WS_TOPOLOGY_FILENAME]
    assert SOURCE_PRECEDENCE[HA_MATTER_WS_TOPOLOGY_FILENAME] > 60


def test_composite_guard_correlates_same_ha_matter_node_across_snapshots() -> None:
    devices_file = "td-ha-matter-ws-devices-fetch-all.json"
    diagnostics_file = "td-ha-matter-ws-diagnostics-fetch-all.json"
    matter = {"compressedFabricId": 0x1234, "nodeId": 1}
    records = _build(
        [devices_file, diagnostics_file],
        {
            devices_file: [{"matter": matter, "deviceLabel": "Sensor"}],
            diagnostics_file: [{"matter": matter, "channel": 15}],
        },
    )

    assert len(records) == 1
    assert records[0]["deviceLabel"] == "Sensor"
    assert records[0]["channel"] == 15


def test_composite_guard_separates_conflicting_ha_fabrics_on_weak_identity() -> None:
    records = _build(
        [HA_MATTER_WS_TOPOLOGY_FILENAME],
        {
            HA_MATTER_WS_TOPOLOGY_FILENAME: [
                {
                    "matter": {"compressedFabricId": 1, "nodeId": 1},
                    "omrIpv6Address": "fd00::1",
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 151}}
                    ],
                },
                {
                    "matter": {"compressedFabricId": 2, "nodeId": 1},
                    "omrIpv6Address": "fd00::1",
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 149}}
                    ],
                },
            ]
        },
    )

    assert len(records) == 2
    assert {
        record["matter"]["compressedFabricId"]: record["powerSources"][0]["attributes"][
            "batPercentRemaining"
        ]
        for record in records
    } == {1: 151, 2: 149}


def test_matter_endpoint_conflicts_retain_higher_priority_source_values() -> None:
    devices_file = HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME
    matter = {"compressedFabricId": 0x1234, "nodeId": 1}
    records = _build(
        [devices_file, HA_MATTER_WS_TOPOLOGY_FILENAME],
        {
            devices_file: [
                {
                    "matter": matter,
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 151}}
                    ],
                }
            ],
            HA_MATTER_WS_TOPOLOGY_FILENAME: [
                {
                    "matter": matter,
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 149}}
                    ],
                }
            ],
        },
    )

    assert len(records) == 1
    assert records[0]["powerSources"][0]["attributes"]["batPercentRemaining"] == 149
    assert records[0]["_merge_conflicts"] == [
        {
            "path": "powerSources[endpointId=2].attributes.batPercentRemaining",
            "current": 149,
            "incoming": 151,
        }
    ]


def test_concrete_extaddress_correlates_ha_and_otbr_records() -> None:
    records = _build(
        [HA_MATTER_WS_TOPOLOGY_FILENAME, OTBR_RESTAPI_DEVICES_FETCH_FILENAME],
        {
            HA_MATTER_WS_TOPOLOGY_FILENAME: [
                {
                    "matter": {"compressedFabricId": 1, "nodeId": 1},
                    "extAddress": "aa00112233445566",
                    "deviceLabel": "Matter Sensor",
                }
            ],
            OTBR_RESTAPI_DEVICES_FETCH_FILENAME: [
                {"extAddress": "aa00112233445566", "role": "child"}
            ],
        },
    )

    assert len(records) == 1
    assert records[0]["extAddress"] == "aa00112233445566"


def test_endpoint_arrays_do_not_cross_merge_on_address_match_with_different_matter_ids() -> None:
    records = _build(
        [HA_MATTER_WS_TOPOLOGY_FILENAME, HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME],
        {
            HA_MATTER_WS_TOPOLOGY_FILENAME: [
                {
                    "matter": {
                        "compressedFabricId": 0x1234,
                        "nodeId": 1,
                        "endpoints": [
                            {
                                "endpointId": 2,
                                "bridgedBasicInformation": {"serialNumber": "FABRIC-A"},
                            }
                        ],
                    },
                    "extAddress": "aa00112233445566",
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 151}}
                    ],
                }
            ],
            HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME: [
                {
                    "matter": {
                        "matterId": "0000000000005678-0000000000000001",
                        "nodeId": 1,
                        "endpoints": [
                            {
                                "endpointId": 2,
                                "bridgedBasicInformation": {"serialNumber": "FABRIC-B"},
                            }
                        ],
                    },
                    "extAddress": "aa00112233445566",
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 149}}
                    ],
                }
            ],
        },
    )

    assert len(records) == 1
    assert records[0]["matter"]["compressedFabricId"] == 0x1234
    assert "matterId" not in records[0]["matter"]
    assert records[0]["matter"]["endpoints"][0]["bridgedBasicInformation"][
        "serialNumber"
    ] == "FABRIC-A"
    assert records[0]["powerSources"][0]["attributes"]["batPercentRemaining"] == 151
    assert {item["path"] for item in records[0]["_merge_conflicts"]} >= {
        "matter",
        "powerSources",
    }


def test_ha_matter_fields_enrich_correlated_non_matter_record() -> None:
    address = "aa00112233445566"
    records = _build(
        [HA_MATTER_WS_TOPOLOGY_FILENAME, OTBR_RESTAPI_DEVICES_FETCH_FILENAME],
        {
            OTBR_RESTAPI_DEVICES_FETCH_FILENAME: [
                {"extAddress": address, "deviceLabel": "Sensor"}
            ],
            HA_MATTER_WS_TOPOLOGY_FILENAME: [
                {
                    "matter": {
                        "compressedFabricId": 0x1234,
                        "nodeId": 1,
                        "endpoints": [{"endpointId": 2, "basicInformation": {}}],
                    },
                    "extAddress": address,
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 151}}
                    ],
                }
            ],
        },
    )

    assert len(records) == 1
    assert records[0]["matter"]["compressedFabricId"] == 0x1234
    assert records[0]["matter"]["endpoints"] == [
        {"endpointId": 2, "basicInformation": {}}
    ]
    assert records[0]["powerSources"][0]["attributes"]["batPercentRemaining"] == 151


def test_nested_matter_object_cannot_replace_conflicting_legacy_identity() -> None:
    address = "aa00112233445566"
    records = _build(
        [HA_MATTER_WS_TOPOLOGY_FILENAME, HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME],
        {
            HA_MATTER_WS_TOPOLOGY_FILENAME: [
                {
                    "matterId": "0000000000001234-0000000000000001",
                    "compressedFabricId": 0x1234,
                    "nodeId": 1,
                    "extAddress": address,
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 151}}
                    ],
                }
            ],
            HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME: [
                {
                    "matter": {
                        "matterId": "0000000000005678-0000000000000001",
                        "compressedFabricId": 0x5678,
                        "nodeId": 1,
                        "endpoints": [
                            {
                                "endpointId": 2,
                                "bridgedBasicInformation": {"serialNumber": "FABRIC-B"},
                            }
                        ],
                    },
                    "extAddress": address,
                    "powerSources": [
                        {"endpointId": 2, "attributes": {"batPercentRemaining": 149}}
                    ],
                }
            ],
        },
    )

    assert len(records) == 1
    assert records[0]["matterId"] == "0000000000001234-0000000000000001"
    assert "matter" not in records[0]
    assert records[0]["powerSources"][0]["attributes"]["batPercentRemaining"] == 151
    assert {item["path"] for item in records[0]["_merge_conflicts"]} >= {
        "matter",
        "powerSources",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_python_and_browser_merge_matter_arrays_by_endpoint_identity() -> None:
    root = Path(__file__).parents[1]
    fixture_path = root / "tests" / "fixtures" / "ha_matter_ws_endpoint_merge.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    python_result = deep_merge(fixture["base"], fixture["incoming"])
    runner = root / "tests" / "js" / "run-ha-matter-ws-endpoint-merge.mjs"
    completed = subprocess.run(
        [shutil.which("node") or "node", str(runner), str(fixture_path)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    browser_result = json.loads(completed.stdout)

    assert browser_result == python_result
    assert [item["endpointId"] for item in python_result["matter"]["endpoints"][:2]] == [1, 2]
    assert [item["endpointId"] for item in python_result["powerSources"][:2]] == [1, 2]
    assert len(python_result["matter"]["endpoints"]) == 4
    assert len(python_result["powerSources"]) == 4
    assert python_result["matter"]["endpoints"][1]["basicInformation"] == {
        "vendorName": "Acme",
        "productName": "Window Sensor",
        "configurationVersion": 0,
    }
    assert python_result["matter"]["endpoints"][1]["bridgedBasicInformation"] == {
        "reachable": False,
        "serialNumber": None,
        "uniqueId": "bridge-node-1",
    }
    assert python_result["powerSources"][0]["batteryPercent"] == 75.5
    assert python_result["powerSources"][0]["attributes"]["endpointList"] == []
    assert python_result["powerSources"][0]["attributes"]["description"] is None
    assert python_result["_merge_conflicts"] == [
        {
            "path": "matter.endpoints[endpointId=2].basicInformation.productName",
            "current": "Window Sensor",
            "incoming": "Conflicting name",
        },
        {
            "path": "matter.endpoints[endpointId=2].basicInformation.configurationVersion",
            "current": 0,
            "incoming": 9,
        },
        {
            "path": "matter.endpoints[endpointId=2].bridgedBasicInformation.reachable",
            "current": False,
            "incoming": True,
        },
        {
            "path": "matter.endpoints[endpointId=2].bridgedBasicInformation.serialNumber",
            "current": None,
            "incoming": "BRIDGE-SENSOR-1",
        },
        {
            "path": "powerSources[endpointId=1].attributes.batPercentRemaining",
            "current": 151,
            "incoming": 149,
        },
        {
            "path": "powerSources[endpointId=1].attributes.endpointList",
            "current": [],
            "incoming": [1],
        },
        {
            "path": "powerSources[endpointId=1].attributes.description",
            "current": None,
            "incoming": "Backup",
        },
        {
            "path": "powerSources[endpointId=1].batteryPercent",
            "current": 75.5,
            "incoming": 74.5,
        },
        {
            "path": "powerSources[endpointId=2].attributes.status",
            "current": 0,
            "incoming": 1,
        },
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_browser_ha_matter_identity_contract() -> None:
    runner = Path(__file__).parent / "js" / "run-ha-matter-ws-phase6.mjs"
    completed = subprocess.run(
        [shutil.which("node") or "node", str(runner)],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {"scenarios": 7}


def test_websockets_dependency_is_packaged_by_both_images() -> None:
    root = Path(__file__).parents[1]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "websockets>=17.3,<18" in requirements

    for dockerfile in (root / "Dockerfile", root / "addon_hobat" / "Dockerfile"):
        content = dockerfile.read_text(encoding="utf-8")
        assert "COPY requirements.txt /tmp/requirements.txt" in content
        assert "pip install --no-cache-dir -r /tmp/requirements.txt" in content


def test_checked_in_snapshots_are_safe_and_registered() -> None:
    root = Path(__file__).parents[1]
    filenames = {
        HA_MATTER_WS_SERVER_INFO_FILENAME,
        HA_MATTER_WS_DEVICES_FETCH_ALL_FILENAME,
        HA_MATTER_WS_DIAGNOSTICS_FETCH_ALL_FILENAME,
        HA_MATTER_WS_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
        HA_MATTER_WS_TOPOLOGY_FILENAME,
        HA_MATTER_WS_COLLECTION_OUTCOME_FILENAME,
    }

    assert filenames <= set(FILE_ACTION_MAP)
    for filename in filenames:
        payload = json.loads((root / "data" / filename).read_text(encoding="utf-8"))
        assert_snapshot_safe(payload)