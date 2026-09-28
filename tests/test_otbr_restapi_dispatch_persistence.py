import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import otbr_restapi_actions as actions_module
import otbr_restapi_devices as devices_module
import otbr_restapi_diagnostics as diagnostics_module
import otbr_restapi_mesh_diagnostics as mesh_module
import otbr_restapi_node as node_module
import otbr_restapi_cli as cli_module
from otbr_restapi_util import OTBRUsageError, emit_rest_command_output
from util_data import read_network_scope


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


def test_node_active_dataset_text_is_redacted_without_file_output():
    client = Mock()
    client.get_active_dataset.return_value = "Network Key: SECRET-NETWORK-KEY"
    args = SimpleNamespace(
        node_command="dataset",
        dataset_kind="active",
        dataset_command="get",
        text=True,
        resolved_output_path=None,
    )

    result = node_module.dispatch_node(client, args, raw_arg=False, fields=None)

    assert result == "[Redacted]"


def test_node_active_dataset_unexpected_text_is_redacted_without_file_output():
    client = Mock()
    client.get_active_dataset.return_value = "Network Key: SECRET-NETWORK-KEY"
    args = SimpleNamespace(
        node_command="dataset",
        dataset_kind="active",
        dataset_command="get",
        text=False,
        resolved_output_path=None,
    )

    result = node_module.dispatch_node(client, args, raw_arg=False, fields=None)

    assert result == "[Redacted]"


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


def test_active_dataset_get_auto_output_publishes_observed_scope(tmp_path, monkeypatch):
    client = Mock()
    client.get_active_dataset.return_value = {
        "extPanId": "78b9775b001c1cbe",
        "networkKey": "SECRET-NETWORK-KEY",
    }
    monkeypatch.setenv("HOBAT_EXT_PAN_ID", "78b9775b001c1cbe")

    with patch.object(cli_module, "build_client", return_value=client):
        assert cli_module.main([
            "--datadir", str(tmp_path), "--raw", "node", "dataset", "active", "get",
        ]) == 0

    output = tmp_path / "td-otbr-restapi-dataset-active.json"
    scope, error = read_network_scope(output)
    assert error is None
    assert scope["provenance"] == "observed"
    assert scope["extPanId"] == "78b9775b001c1cbe"
    assert json.loads(output.read_text(encoding="utf-8"))["networkKey"] == "[Redacted]"
    client.get_active_dataset.assert_called_once_with(plain_text=False, raw=True)


def test_active_dataset_auto_output_respects_output_modes(tmp_path):
    command = ["node", "dataset", "active", "get"]
    for argv in (
        command + ["--text"],
        ["--no-auto-output"] + command,
        ["--output", "custom.json"] + command,
        ["node", "state", "get"],
    ):
        args = cli_module.build_parser().parse_args(argv)
        assert cli_module._auto_output_path(args, tmp_path) is None


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


def test_rest_command_output_replaces_final_for_structured_partial_result_with_records(tmp_path):
    output_path = tmp_path / "result.json"
    output_path.write_text('[{"id":"old"}]', encoding="utf-8")
    payload = {
        "items": [{"id": "fresh"}],
        "deviceResults": [{"status": "partial"}],
        "partial": True,
    }

    assert emit_rest_command_output(payload, output_path) is payload

    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


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


def test_devices_dispatch_normalizes_border_router_alias_conflicts(tmp_path):
    payload = [{
        "id": "dev-1",
        "isBorderRouter": False,
        "is_border_router": True,
        "br": False,
    }]
    client = Mock()
    client.list_devices.return_value = payload
    output_path = tmp_path / "td-otbr-restapi-devices-list.json"
    args = SimpleNamespace(
        devices_command="list",
        with_meta=False,
        resolved_output_path=str(output_path),
    )

    result = devices_module.dispatch_devices(client, args, raw_arg=False, fields=None)

    assert result[0]["isBorderRouter"] is False
    assert "br" not in result[0]
    assert "is_border_router" not in result[0]
    assert result[0]["_merge_conflicts"] == [
        {"path": "isBorderRouter", "current": False, "incoming": True}
    ]
    [saved] = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved == result[0]


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


def test_diagnostics_fetch_all_preserves_roles_for_explicit_device_ids():
    devices = [
        {"id": "1111111111111111", "role": "child"},
        {"id": "2222222222222222", "role": "router"},
    ]
    outcome = {"items": [], "deviceResults": [], "partial": False}
    client = Mock()
    client.list_devices.return_value = devices
    client.fetch_all_devices_diagnostics.return_value = outcome
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "diagnostics",
            "fetch-all",
            "--device-ids",
            "1111111111111111",
            "2222222222222222",
            "--no-update-devices",
            "--preserve-diagnostics",
            "--no-basic-fallback",
        ]
    )

    with patch.object(diagnostics_module, "emit_rest_command_output", return_value=outcome):
        result = diagnostics_module.dispatch_diagnostics(client, args, False, None)

    assert result is outcome
    client.list_devices.assert_called_once_with(raw=False)
    selected_devices = client.fetch_all_devices_diagnostics.call_args.args[0]
    assert selected_devices == devices
    assert [device["role"] for device in selected_devices] == ["child", "router"]
    assert client.fetch_all_devices_diagnostics.call_args.kwargs["progressive_fallback"] is True
    assert client.fetch_all_devices_diagnostics.call_args.kwargs["include_basic_fallback"] is False


def test_diagnostics_fetch_all_checkpoint_and_final_preserve_address_override(tmp_path):
    output_path = tmp_path / "td-otbr-restapi-diagnostics-fetch-all.json"
    source_record = {
        "id": "device-1",
        "isBorderRouter": False,
        "ipv6Addresses": ["fdde:ad00:beef:0:0:ff:fe00:fc11"],
    }
    client = Mock()
    client.list_devices.return_value = [{"id": "device-1"}]

    def fetch_all(*_args, **kwargs):
        kwargs["on_checkpoint"]([dict(source_record)], 1, 1, "device-1", "completed")
        return {
            "items": [dict(source_record)],
            "deviceResults": [{"deviceId": "device-1", "status": "completed"}],
            "partial": False,
        }

    client.fetch_all_devices_diagnostics.side_effect = fetch_all
    args = SimpleNamespace(
        diagnostics_command="fetch-all",
        no_enrich_mac_counters=False,
        no_update_devices=True,
        device_ids=None,
        destination_type="extended",
        task_timeout=8,
        poll_interval=2.0,
        poll_timeout=8.0,
        no_progress=True,
        no_fallback=True,
        no_basic_fallback=False,
        preset="recommended",
        fallback_preset=None,
        types=None,
        preserve_diagnostics=False,
        items_only=True,
        resolved_output_path=str(output_path),
    )

    diagnostics_module.dispatch_diagnostics(client, args, False, None)

    checkpoint_path = tmp_path / "td-otbr-restapi-diagnostics-fetch-all.partial.json"
    for path in (checkpoint_path, output_path):
        [saved] = json.loads(path.read_text(encoding="utf-8"))
        assert saved["isBorderRouter"] is True
        assert "br" not in saved
        assert "is_border_router" not in saved
        assert saved["_merge_conflicts"] == [
            {"path": "isBorderRouter", "current": False, "incoming": True}
        ]


@pytest.mark.parametrize(
    "policy_args",
    [
        ["--no-fallback"],
        ["--fallback-preset", "medium"],
        ["--types", "extAddress"],
        ["--preset", "minimal"],
    ],
)
def test_no_basic_fallback_requires_progressive_policy(policy_args):
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "diagnostics",
            "fetch-all",
            "--no-basic-fallback",
            *policy_args,
        ]
    )
    client = Mock()

    with pytest.raises(OTBRUsageError, match="requires the default or recommended progressive"):
        diagnostics_module.dispatch_diagnostics(client, args, False, None)

    client.list_devices.assert_not_called()


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


def test_router_filter_prefers_explicit_role_and_falls_back_to_rloc16(caplog):
    devices = [
        {"id": "router-role", "role": "router"},
        {"id": "child-role", "role": "child"},
        {
            "id": "reed-child",
            "role": "child",
            "mode": {
                "fullThreadDevice": True,
                "rxOnWhenIdle": True,
                "fullNetworkData": True,
            },
        },
        {"id": "rloc-router", "rloc16": "0x1400"},
        {"id": "rloc-child", "rloc16": "0x1401"},
        {"id": "invalid-rloc", "rloc16": "invalid"},
        {"id": "unclassified-no-rloc"},
        {"id": "unknown-role", "role": "leader", "rloc16": "0x1800"},
    ]

    selected = mesh_module.filter_router_device_ids(
        devices,
        [device["id"] for device in devices] + ["missing-device"],
    )

    assert selected == ["router-role", "rloc-router"]
    assert "reed-child" not in selected
    assert "invalid-rloc" in caplog.text
    assert "unclassified-no-rloc" in caplog.text
    assert "unknown-role" in caplog.text
    assert "missing-device" in caplog.text


def test_mesh_fetch_all_routers_only_uses_strict_filter():
    devices = [
        {"id": "router-role", "role": "router"},
        {"id": "child-role", "role": "child"},
        {"id": "rloc-router", "rloc16": "0x1400"},
        {"id": "unclassified", "rloc16": "invalid"},
    ]
    outcome = {"items": [], "deviceResults": [], "partial": False}
    client = Mock()
    client.list_devices.return_value = devices
    client.fetch_mesh_diagnostics_all_devices.return_value = outcome
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "mesh-diagnostics",
            "fetch-all",
            "--no-update-devices",
        ]
    )
    assert args.routers_only is True

    with patch.object(mesh_module, "emit_rest_command_output", return_value=outcome):
        result = mesh_module.dispatch_mesh_diagnostics(client, args, False)

    assert result is outcome
    client.list_devices.assert_called_once_with(raw=False)
    assert client.fetch_mesh_diagnostics_all_devices.call_args.args[0] == [
        "router-role",
        "rloc-router",
    ]


def test_mesh_fetch_all_all_devices_opt_out_bypasses_router_filter():
    devices = [
        {"id": "router-role", "role": "router"},
        {"id": "child-role", "role": "child"},
        {"id": "rloc-router", "rloc16": "0x1400"},
    ]
    outcome = {"items": [], "deviceResults": [], "partial": False}
    client = Mock()
    client.list_devices.return_value = devices
    client.fetch_mesh_diagnostics_all_devices.return_value = outcome
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "mesh-diagnostics",
            "fetch-all",
            "--no-update-devices",
            "--all-devices",
        ]
    )

    with patch.object(mesh_module, "emit_rest_command_output", return_value=outcome):
        result = mesh_module.dispatch_mesh_diagnostics(client, args, False)

    assert result is outcome
    assert args.routers_only is False
    client.fetch_mesh_diagnostics_all_devices.assert_called_once()
    assert client.fetch_mesh_diagnostics_all_devices.call_args.args[0] == [
        "router-role",
        "child-role",
        "rloc-router",
    ]


def test_mesh_fetch_all_forwards_items_only_and_returns_item_array():
    items = [{"id": "diag-mesh", "extAddress": "router-role", "children": []}]
    client = Mock()
    client.list_devices.return_value = [{"id": "router-role", "role": "router"}]
    client.fetch_mesh_diagnostics_all_devices.return_value = items
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "mesh-diagnostics",
            "fetch-all",
            "--no-update-devices",
            "--items-only",
            "--preserve-diagnostics",
        ]
    )

    with patch.object(mesh_module, "emit_rest_command_output", return_value=items):
        result = mesh_module.dispatch_mesh_diagnostics(client, args, False)

    assert result is items
    client.fetch_mesh_diagnostics_all_devices.assert_called_once()
    assert client.fetch_mesh_diagnostics_all_devices.call_args.kwargs["items_only"] is True
    assert client.fetch_mesh_diagnostics_all_devices.call_args.kwargs["clear_diagnostics"] is False


def test_mesh_fetch_all_routers_only_selector_remains_accepted():
    args = cli_module.build_parser().parse_args(
        ["mesh-diagnostics", "fetch-all", "--routers-only"]
    )

    assert args.routers_only is True