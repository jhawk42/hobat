from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import otbr_cli_meshdiag_childip6 as cli_childip6
import otbr_cli_meshdiag_childtable as cli_childtable
import otbr_cli_meshdiag_routerneighbortable as cli_neighbors
import otbr_restapi_devices as devices_module
import otbr_restapi_diagnostics as diagnostics_module
import otbr_restapi_mesh_diagnostics as mesh_module


def test_devices_fetch_writes_checkpoint_when_output_path_is_resolved() -> None:
    client = Mock()
    client.fetch_device_collection.return_value = [{"id": "dev-1"}]
    args = SimpleNamespace(
        devices_command="fetch",
        device_count=255,
        max_age=60,
        max_retries=2,
        task_timeout=8,
        poll_interval=2.0,
        poll_timeout=8.0,
        resolved_output_path="/tmp/td-otbr-restapi-devices-fetch.json",
    )

    with patch.object(devices_module, "_write_checkpoint_best_effort") as checkpoint_write:
        result = devices_module.dispatch_devices(client, args, raw_arg=False, fields=None)

    assert result == [{"id": "dev-1"}]
    checkpoint_write.assert_called_once()
    payload, checkpoint_path = checkpoint_write.call_args.args
    assert payload == [{"id": "dev-1"}]
    assert checkpoint_path == Path("/tmp/td-otbr-restapi-devices-fetch.partial.json")


def test_diagnostics_fetch_all_invokes_checkpoint_callback_when_output_path_is_resolved() -> None:
    client = Mock()
    client.list_devices.return_value = [{"id": "dev-1"}]

    args = SimpleNamespace(
        diagnostics_command="fetch-all",
        no_enrich_mac_counters=True,
        no_update_devices=True,
        device_ids=None,
        destination_type="extended",
        task_timeout=8,
        poll_interval=2.0,
        poll_timeout=8.0,
        no_progress=True,
        no_fallback=True,
        preset="recommended",
        types=None,
        resolved_output_path="/tmp/td-otbr-restapi-diagnostics-fetch-all.json",
        items_only=True,
    )

    def _fake_fetch_all_devices_diagnostics(*_args, **kwargs):
        on_checkpoint = kwargs.get("on_checkpoint")
        assert on_checkpoint is not None
        on_checkpoint([{"id": "diag-1"}], 1, 1, "dev-1", "completed")
        return {
            "items": [{"id": "diag-1"}],
            "deviceResults": [{"deviceId": "dev-1", "status": "completed"}],
            "partial": False,
        }

    client.fetch_all_devices_diagnostics.side_effect = _fake_fetch_all_devices_diagnostics
    with patch.object(diagnostics_module, "_write_checkpoint_best_effort") as checkpoint_write:
        result = diagnostics_module.dispatch_diagnostics(client, args, raw_arg=False, fields=None)

    assert isinstance(result, list)
    checkpoint_write.assert_called_once()
    payload, checkpoint_path, command_name, stage = checkpoint_write.call_args.args
    assert payload == [{"id": "diag-1"}]
    assert checkpoint_path == Path("/tmp/td-otbr-restapi-diagnostics-fetch-all.partial.json")
    assert command_name == "otbr-restapi diagnostics fetch-all"
    assert stage == "device"


def test_mesh_diagnostics_fetch_all_invokes_checkpoint_callback_when_output_path_is_resolved() -> None:
    client = Mock()
    client.list_devices.return_value = [{"id": "dev-1", "rloc16": "0x4000"}]

    args = SimpleNamespace(
        mesh_diag_command="fetch-all",
        poll_timeout=8.0,
        poll_interval=2.0,
        destination_type="extended",
        task_timeout=8,
        types=None,
        no_update_devices=True,
        routers_only=False,
        device_ids=None,
        no_progress=True,
        items_only=True,
        resolved_output_path="/tmp/td-otbr-restapi-mesh-diagnostics-fetch-all.json",
    )

    def _fake_fetch_mesh_all(*_args, **kwargs):
        on_checkpoint = kwargs.get("on_checkpoint")
        assert on_checkpoint is not None
        on_checkpoint([{"id": "mesh-1"}], 1, 1, "dev-1", "completed")
        return {
            "items": [{"id": "mesh-1"}],
            "deviceResults": [{"deviceId": "dev-1", "status": "completed"}],
            "partial": False,
        }

    client.fetch_mesh_diagnostics_all_devices.side_effect = _fake_fetch_mesh_all

    with patch.object(mesh_module, "_write_checkpoint_best_effort") as checkpoint_write:
        result = mesh_module.dispatch_mesh_diagnostics(client, args, raw_arg=False)

    assert result == [{"id": "mesh-1"}]
    checkpoint_write.assert_called_once()
    payload, checkpoint_path = checkpoint_write.call_args.args
    assert payload == [{"id": "mesh-1"}]
    assert checkpoint_path == Path("/tmp/td-otbr-restapi-mesh-diagnostics-fetch-all.partial.json")


@pytest.mark.parametrize(
    ("module", "helper_args"),
    [
        (devices_module, ([{"id": "dev-1"}], Path("/tmp/devices.partial.json"))),
        (
            diagnostics_module,
            (
                [{"id": "diag-1"}],
                Path("/tmp/diagnostics.partial.json"),
                "otbr-restapi diagnostics fetch-all",
                "device",
            ),
        ),
        (mesh_module, ([{"id": "mesh-1"}], Path("/tmp/mesh.partial.json"))),
        (cli_childip6, ([], Path("/tmp/childip6.partial.json"))),
        (cli_childtable, ([], Path("/tmp/childtable.partial.json"))),
        (cli_neighbors, ([], Path("/tmp/neighbors.partial.json"))),
    ],
)
def test_best_effort_checkpoint_write_failures_warn_and_continue(
    caplog, module, helper_args
):
    with patch.object(
        module, "save_json_atomic", side_effect=OSError("checkpoint disk full")
    ):
        module._write_checkpoint_best_effort(*helper_args)

    assert "checkpoint_write_failed" in caplog.text
    assert "action=continue_best_effort" in caplog.text


def test_rest_fetch_dispatchers_do_not_checkpoint_without_output_path() -> None:
    devices_client = Mock()
    devices_client.fetch_device_collection.return_value = [{"id": "dev-1"}]
    devices_args = SimpleNamespace(
        devices_command="fetch",
        device_count=255,
        max_age=60,
        max_retries=2,
        task_timeout=8,
        poll_interval=2.0,
        poll_timeout=8.0,
        resolved_output_path=None,
    )

    diagnostics_client = Mock()
    diagnostics_client.list_devices.return_value = [{"id": "dev-1"}]
    diagnostics_client.fetch_all_devices_diagnostics.return_value = {
        "items": [{"id": "diag-1"}],
        "deviceResults": [],
        "partial": False,
    }
    diagnostics_args = SimpleNamespace(
        diagnostics_command="fetch-all",
        no_enrich_mac_counters=True,
        no_update_devices=True,
        device_ids=None,
        destination_type="extended",
        task_timeout=8,
        poll_interval=2.0,
        poll_timeout=8.0,
        no_progress=True,
        no_fallback=True,
        preset="recommended",
        types=None,
        resolved_output_path=None,
        items_only=True,
    )

    mesh_client = Mock()
    mesh_client.list_devices.return_value = [{"id": "dev-1", "rloc16": "0x4000"}]
    mesh_client.fetch_mesh_diagnostics_all_devices.return_value = {
        "items": [{"id": "mesh-1"}],
        "deviceResults": [],
        "partial": False,
    }
    mesh_args = SimpleNamespace(
        mesh_diag_command="fetch-all",
        poll_timeout=8.0,
        poll_interval=2.0,
        destination_type="extended",
        task_timeout=8,
        types=None,
        no_update_devices=True,
        routers_only=False,
        device_ids=None,
        no_progress=True,
        items_only=True,
        resolved_output_path=None,
    )

    with patch.object(devices_module, "_write_checkpoint_best_effort") as devices_write, patch.object(
        diagnostics_module, "_write_checkpoint_best_effort"
    ) as diagnostics_write, patch.object(
        mesh_module, "_write_checkpoint_best_effort"
    ) as mesh_write:
        assert devices_module.dispatch_devices(
            devices_client, devices_args, raw_arg=False, fields=None
        ) == [{"id": "dev-1"}]
        assert diagnostics_module.dispatch_diagnostics(
            diagnostics_client, diagnostics_args, raw_arg=False, fields=None
        ) == [{"id": "diag-1"}]
        assert mesh_module.dispatch_mesh_diagnostics(
            mesh_client, mesh_args, raw_arg=False
        ) == [{"id": "mesh-1"}]

    devices_write.assert_not_called()
    diagnostics_write.assert_not_called()
    mesh_write.assert_not_called()
