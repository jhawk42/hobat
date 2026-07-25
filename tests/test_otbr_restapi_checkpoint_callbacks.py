from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
