from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import otbr_restapi_cli as cli_module
import otbr_restapi_topology as topology_module
from td_const import (
    OTBR_RESTAPI_DEVICES_FETCH_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)


def test_topology_saves_each_enabled_output_before_the_next_collection(tmp_path):
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "topology",
            "--no-update-devices",
            "--no-enrich-mac-counters",
        ]
    )
    args.td_data_dir = tmp_path
    events = []
    client = MagicMock()
    devices = [{"id": "dev-1", "rloc16": "0x4000"}]
    diagnostics_outcome = {
        "items": [{"id": "diag-1"}],
        "deviceResults": [],
        "partial": False,
    }
    mesh_outcome = {
        "items": [{"id": "mesh-1"}],
        "deviceResults": [],
        "partial": False,
    }
    client.fetch_device_collection.side_effect = (
        lambda **_kwargs: events.append("collect:devices") or devices
    )
    client.fetch_all_devices_diagnostics.side_effect = (
        lambda *_args, **_kwargs: events.append("collect:diagnostics")
        or diagnostics_outcome
    )
    client.fetch_mesh_diagnostics_all_devices.side_effect = (
        lambda *_args, **_kwargs: events.append("collect:mesh") or mesh_outcome
    )

    def save(_payload, path, _logger):
        events.append(f"save:{path.name}")

    with patch.object(topology_module, "emit_rest_payload_output", side_effect=save):
        result = topology_module.dispatch_topology(client, args, raw_arg=False)
        events.append("returned")

    assert result is None
    assert events == [
        "collect:devices",
        f"save:{OTBR_RESTAPI_DEVICES_FETCH_FILENAME}",
        "collect:diagnostics",
        f"save:{OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME}",
        f"save:{OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME}",
        "collect:mesh",
        f"save:{OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME}",
        f"save:{OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME}",
        "returned",
    ]


def test_topology_mandatory_save_failure_stops_before_next_collection(tmp_path):
    args = cli_module.build_parser().parse_args(
        ["--no-progress", "topology", "--no-enrich-mac-counters"]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    client.fetch_device_collection.return_value = [
        {"id": "dev-1", "rloc16": "0x4000"}
    ]

    with patch.object(
        topology_module,
        "emit_rest_payload_output",
        side_effect=OSError("disk full"),
    ):
        try:
            topology_module.dispatch_topology(client, args, raw_arg=False)
        except OSError as exc:
            assert str(exc) == "disk full"
        else:
            raise AssertionError("mandatory save failure did not propagate")

    client.fetch_all_devices_diagnostics.assert_not_called()
    client.fetch_mesh_diagnostics_all_devices.assert_not_called()


def test_topology_skip_devices_keeps_device_inputs_unsaved(tmp_path):
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "topology",
            "--skip-devices",
            "--no-enrich-mac-counters",
        ]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    client.list_devices.return_value = [{"id": "listed", "rloc16": "0x4000"}]
    client.fetch_device_collection.return_value = [
        {"id": "refreshed", "rloc16": "0x4400"}
    ]
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [{"id": "diag-1"}],
        "deviceResults": [],
        "partial": False,
    }
    client.fetch_mesh_diagnostics_all_devices.return_value = {
        "items": [{"id": "mesh-1"}],
        "deviceResults": [],
        "partial": False,
    }
    saved_paths = []

    with patch.object(
        topology_module,
        "emit_rest_payload_output",
        side_effect=lambda _payload, path, _logger: saved_paths.append(path.name),
    ):
        assert topology_module.dispatch_topology(client, args, raw_arg=False) is None

    client.list_devices.assert_called_once_with(raw=False)
    client.fetch_device_collection.assert_called_once_with(items_only=True)
    assert OTBR_RESTAPI_DEVICES_FETCH_FILENAME not in saved_paths
    assert saved_paths == [
        OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
        OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
        OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
        OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
    ]


@pytest.mark.parametrize(
    ("command_args", "expected_updates"),
    [
        ([], 1),
        (["--skip-devices"], 1),
        (["--no-update-devices"], 1),
        (["--skip-devices", "--no-update-devices"], 0),
    ],
)
def test_topology_updates_device_collection_at_most_once(tmp_path, command_args, expected_updates):
    args = cli_module.build_parser().parse_args(
        ["--no-progress", "topology", "--no-enrich-mac-counters", *command_args]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    devices = [{"id": "dev-1", "rloc16": "0x4000"}]
    client.fetch_device_collection.return_value = devices
    client.list_devices.return_value = devices
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }
    client.fetch_mesh_diagnostics_all_devices.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }

    topology_module.dispatch_topology(client, args, raw_arg=False)

    assert client.fetch_device_collection.call_count == expected_updates
    assert client.fetch_device_collection.call_count <= 1


def test_topology_run_cli_does_not_add_a_generic_final_write(tmp_path):
    with patch.object(cli_module, "build_client", return_value=MagicMock()), patch.object(
        cli_module, "dispatch_topology", return_value=None
    ), patch.object(
        cli_module.Path,
        "write_text",
        side_effect=AssertionError("run_cli attempted a generic topology write"),
    ):
        result = cli_module.main(["--datadir", str(tmp_path), "topology"])

    assert result == cli_module.EXIT_SUCCESS