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
                },
                {
                    "matter": {"compressedFabricId": 2, "nodeId": 2},
                    "omrIpv6Address": "fd00::1",
                },
            ]
        },
    )

    assert len(records) == 2


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

    assert json.loads(completed.stdout) == {"scenarios": 4}


def test_websockets_dependency_is_packaged_by_both_images() -> None:
    root = Path(__file__).parents[1]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "websockets>=16.0,<17" in requirements

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