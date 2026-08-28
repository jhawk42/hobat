from __future__ import annotations

from unittest.mock import MagicMock, patch

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