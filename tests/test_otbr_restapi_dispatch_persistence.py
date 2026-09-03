import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import otbr_restapi_actions as actions_module
import otbr_restapi_devices as devices_module
import otbr_restapi_diagnostics as diagnostics_module
import otbr_restapi_mesh_diagnostics as mesh_module
import otbr_restapi_node as node_module
from otbr_restapi_util import emit_rest_command_output


def test_node_dispatch_saves_json_before_return():
    events = []
    payload = {"node_id": "node-1"}
    client = Mock()
    client.get_node.side_effect = lambda **_kwargs: events.append("collect") or payload
    args = SimpleNamespace(
        node_command="get",
        resolved_output_path="/tmp/node.json",
    )

    def save(result, output_path, **kwargs):
        assert result is payload
        assert output_path == "/tmp/node.json"
        assert kwargs.get("plain_text", False) is False
        events.append("save")
        return result

    with patch.object(node_module, "emit_rest_command_output", side_effect=save):
        result = node_module.dispatch_node(client, args, raw_arg=False, fields=None)
        events.append("returned")

    assert result is payload
    assert events == ["collect", "save", "returned"]


def test_node_active_dataset_text_uses_atomic_text_mode():
    client = Mock()
    client.get_active_dataset.return_value = "0e0800"
    args = SimpleNamespace(
        node_command="dataset",
        dataset_kind="active",
        dataset_command="get",
        text=True,
        resolved_output_path="/tmp/dataset.txt",
    )

    with patch.object(
        node_module,
        "emit_rest_command_output",
        side_effect=lambda result, *_args, **_kwargs: result,
    ) as save:
        assert (
            node_module.dispatch_node(client, args, raw_arg=False, fields=None)
            == "[Redacted]"
        )

    assert save.call_args.kwargs["plain_text"] is True


def test_node_active_dataset_json_redacts_file_output():
    client = Mock()
    client.get_active_dataset.return_value = {
        "networkKey": "SECRET-NETWORK-KEY",
        "networkName": "test-network",
        "pskc": "SECRET-PSKC",
    }
    args = SimpleNamespace(
        node_command="dataset",
        dataset_kind="active",
        dataset_command="get",
        text=False,
        resolved_output_path="/tmp/dataset.json",
    )

    with patch.object(
        node_module,
        "emit_rest_command_output",
        side_effect=lambda result, *_args, **_kwargs: result,
    ):
        result = node_module.dispatch_node(client, args, raw_arg=False, fields=None)

    assert result == {
        "networkKey": "[Redacted]",
        "networkName": "test-network",
        "pskc": "[Redacted]",
    }


def test_node_dispatch_without_output_path_remains_side_effect_free():
    payload = {"node_id": "node-1"}
    client = Mock()
    client.get_node.return_value = payload
    args = SimpleNamespace(node_command="get", resolved_output_path=None)

    with patch.object(node_module, "emit_rest_command_output", wraps=node_module.emit_rest_command_output) as save:
        result = node_module.dispatch_node(client, args, raw_arg=False, fields=None)

    assert result is payload
    save.assert_called_once()


def test_rest_command_output_writes_atomic_camel_case_json(tmp_path):
    output_path = tmp_path / "result.json"
    payload = {"device_id": "dev-1"}

    assert emit_rest_command_output(payload, output_path) is payload

    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "deviceId": "dev-1"
    }
    assert not (tmp_path / "result.json.tmp").exists()


def test_rest_command_output_writes_atomic_unquoted_text(tmp_path):
    output_path = tmp_path / "dataset.txt"

    assert emit_rest_command_output("0e0800", output_path, plain_text=True) == "0e0800"

    assert output_path.read_text(encoding="utf-8") == "0e0800\n"
    assert not (tmp_path / "dataset.txt.tmp").exists()


def test_devices_dispatch_owns_final_output():
    payload = [{"id": "dev-1"}]
    client = Mock()
    client.list_devices.return_value = payload
    args = SimpleNamespace(
        devices_command="list",
        with_meta=False,
        resolved_output_path="/tmp/devices.json",
    )

    with patch.object(devices_module, "emit_rest_command_output", return_value=payload) as save:
        result = devices_module.dispatch_devices(client, args, False, None)

    assert result is payload
    save.assert_called_once()


def test_diagnostics_dispatch_owns_final_output_after_normalization():
    payload = {"diagnostic_id": "diag-1"}
    client = Mock()
    client.get_diagnostic.return_value = payload
    args = SimpleNamespace(
        diagnostics_command="get",
        diagnostics_id="diag-1",
        resolved_output_path="/tmp/diagnostics.json",
    )

    with patch.object(diagnostics_module, "emit_rest_command_output", return_value=payload) as save:
        result = diagnostics_module.dispatch_diagnostics(client, args, False, None)

    assert result is payload
    save.assert_called_once()


def test_actions_dispatch_owns_final_output():
    payload = [{"id": "action-1"}]
    client = Mock()
    client.list_actions.return_value = payload
    args = SimpleNamespace(
        actions_command="list",
        with_meta=False,
        resolved_output_path="/tmp/actions.json",
    )

    with patch.object(actions_module, "emit_rest_command_output", return_value=payload) as save:
        result = actions_module.dispatch_actions(client, args, False, None, False)

    assert result is payload
    save.assert_called_once()


def test_mesh_diagnostics_dispatch_owns_final_output():
    payload = {"id": "diag-1"}
    client = Mock()
    client.fetch_mesh_diagnostics.return_value = payload
    args = SimpleNamespace(
        mesh_diag_command="children",
        device_id="dev-1",
        poll_timeout=8,
        poll_interval=1,
        destination_type="extended",
        task_timeout=8,
        resolved_output_path="/tmp/mesh.json",
    )

    with patch.object(mesh_module, "emit_rest_command_output", return_value=payload) as save:
        result = mesh_module.dispatch_mesh_diagnostics(client, args, False)

    assert result is payload
    save.assert_called_once()