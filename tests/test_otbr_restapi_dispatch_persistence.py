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
from otbr_restapi_util import _RAW_UNSET
from td_const import (
    OTBR_RESTAPI_DATASET_ACTIVE_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)
from util_data import (
    CollectionWriteOutcome,
    TD_EXT_PAN_ID_ENV_VAR,
    network_scope_path,
    read_network_scope,
    save_final_json,
)


@pytest.mark.parametrize("rloc", ["0000", "0400", "0800", "f800", "0xF800", 0x0800])
def test_router_inference_preserves_explicit_roles_and_flags(rloc):
    record = {"rloc16": rloc, "role": "child", "isRouter": False}
    diagnostics_module.enrich_border_router(record)
    assert record["role"] == "child"
    assert record["isRouter"] is False
    assert "is_router" not in record
    assert {"path": "role", "current": "child", "incoming": "router"} in record["_merge_conflicts"]
    assert {"path": "isRouter", "current": False, "incoming": True} in record["_merge_conflicts"]
    for role in ("leader", "border router"):
        explicit = {"rloc16": rloc, "role": role}
        diagnostics_module.enrich_border_router(explicit)
        assert explicit["role"] == role


@pytest.mark.parametrize("command", ["list", "fetch", "fetch-all"])
@pytest.mark.parametrize("raw", [False, True])
def test_role_boundaries_through_dispatch_and_persistence(tmp_path, command, raw):
    records = [
        *({"rloc16": value} for value in ("0000", "0400", "0800", "f800", "0xF800", 0x0800)),
        *({"rloc16": value, "role": "child", "mode": {"device": "FTD"}}
          for value in ("0401", "04ff", "0500", "05ff")),
        *({"rloc16": value} for value in (None, "bad-hex", True, "fffe", "ffff", 1024.5)),
    ]
    original = json.loads(json.dumps(records))
    client = Mock()
    client.list_diagnostics.return_value = records
    client.fetch_device_collection.return_value = [{"id": "device"}]
    output = tmp_path / "diagnostics.json"
    args = SimpleNamespace(
        diagnostics_command=command, with_meta=False, device_id="device",
        destination_type="extended", task_timeout=8, poll_interval=0.5,
        poll_timeout=13, no_progress=True, resolved_output_path=output,
    )
    checkpoints = []

    def fetch_all(*_args, **kwargs):
        kwargs["on_checkpoint"](records, 1, 1, "device", "ok")
        checkpoints.extend(json.loads((tmp_path / "diagnostics.partial.json").read_text()))
        return {"items": records}

    client.fetch_all_devices_diagnostics.side_effect = fetch_all
    # Single-device fetch is checked once per record through its actual dispatcher.
    inputs = records if command == "fetch" else [records]
    with patch.object(diagnostics_module, "fetch_device_with_fallback") as fetch:
        for index, payload in enumerate(inputs):
            fetch.return_value = payload
            result = diagnostics_module.dispatch_diagnostics(
                client, args, True if raw else _RAW_UNSET, None,
            )
            saved = json.loads(output.read_text())
            assert saved == result
            if raw:
                assert (result["items"] if command == "fetch-all" else result) is payload
                assert payload == (original[index] if command == "fetch" else original)
                continue
            items = [result] if command == "fetch" else (
                result["items"] if command == "fetch-all" else result
            )
            for item in items:
                value = item.get("rloc16")
                if value in ("0000", "0400", "0800", "f800", "0xf800", 0x0800):
                    assert item["isRouter"] is True
                    assert item["role"] == "router"
                else:
                    assert item.get("isRouter") is not True
                assert "is_router" not in item
                if item.get("role") == "child":
                    assert item.get("isRouter") is not True
    if command == "fetch-all":
        assert checkpoints == (original if raw else result["items"])
        if not raw:
            assert all(item["isReed"] is True for item in checkpoints if item.get("role") == "child")


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
    monkeypatch.setenv("TD_EXT_PAN_ID", "1111111111111111")

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


def test_final_snapshot_scope_uses_td_ext_pan_id_as_operator_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("TD_EXT_PAN_ID", "78b9775b001c1cbe")
    monkeypatch.delenv("HOBAT_EXT_PAN_ID", raising=False)
    output = tmp_path / "td-otbr-restapi-dataset-active.json"

    assert save_final_json({}, output, CollectionWriteOutcome.complete())

    scope, error = read_network_scope(output)
    assert error is None
    assert scope["provenance"] == "operator"
    assert scope["extPanId"] == "78b9775b001c1cbe"


def test_explicit_ext_pan_id_argument_precedes_environment_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("TD_EXT_PAN_ID", "1111111111111111")
    output = tmp_path / "td-otbr-restapi-dataset-active.json"

    assert save_final_json(
        {}, output, CollectionWriteOutcome.complete(), ext_pan_id="78b9775b001c1cbe"
    )

    scope, error = read_network_scope(output)
    assert error is None
    assert scope["provenance"] == "operator"
    assert scope["extPanId"] == "78b9775b001c1cbe"


def test_legacy_environment_name_is_ignored_and_missing_scope_is_unknown(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TD_EXT_PAN_ID", raising=False)
    monkeypatch.setenv("HOBAT_EXT_PAN_ID", "78b9775b001c1cbe")
    output = tmp_path / "td-otbr-restapi-dataset-active.json"

    assert save_final_json({}, output, CollectionWriteOutcome.complete())

    scope, error = read_network_scope(output)
    assert error is None
    assert scope["provenance"] == "unknown"
    assert scope["extPanId"] is None


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
        "type": "child",
        "mode": {"device": "FTD"},
        "isReed": False,
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
        {"path": "isBorderRouter", "current": False, "incoming": True},
        {"path": "isReed", "current": False, "incoming": True},
    ]
    assert result[0]["isReed"] is False
    assert result[0]["_merge_conflicts"][-1] == {
        "path": "isReed", "current": False, "incoming": True
    }
    [saved] = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved == result[0]


def test_devices_fetch_persists_reed_evidence_in_checkpoint_and_final(tmp_path):
    record = {
        "id": "dev-1",
        "role": "child",
        "mode": {"device": "FTD"},
    }
    client = Mock()
    client.fetch_device_collection.return_value = {
        "items": [record],
        "partial": True,
    }
    output_path = tmp_path / "devices-fetch.json"
    args = SimpleNamespace(
        devices_command="fetch",
        device_count=255,
        max_age=None,
        max_retries=1,
        task_timeout=8,
        poll_interval=2.0,
        poll_timeout=13.0,
        resolved_output_path=str(output_path),
        structured_outcome=True,
    )

    result = devices_module.dispatch_devices(client, args, raw_arg=False, fields=None)

    checkpoint_path = tmp_path / "devices-fetch.partial.json"
    for path in (checkpoint_path, output_path):
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["items"][0]["isReed"] is True
    assert result["items"][0]["isReed"] is True


def test_devices_list_raw_bypasses_reed_enrichment():
    payload = [{"role": "child", "mode": {"device": "FTD"}}]
    client = Mock()
    client.list_devices.return_value = payload
    args = SimpleNamespace(
        devices_command="list",
        with_meta=False,
        resolved_output_path=None,
    )

    result = devices_module.dispatch_devices(client, args, raw_arg=True, fields=None)

    assert result is payload
    assert "isReed" not in result[0]


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
        {
            "id": "1111111111111111",
            "role": "child",
            "mlEidIid": "0000000000000000",
        },
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
        "role": "child",
        "mode": {"device": "FTD"},
        "isReed": False,
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
        poll_timeout=13.0,
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
            {"path": "isReed", "current": False, "incoming": True},
            {"path": "isBorderRouter", "current": False, "incoming": True},
        ]
        assert saved["isReed"] is False


@pytest.mark.parametrize(
    ("output_name", "outcome_name"),
    [
        (
            "diagnostics-export.json",
            "diagnostics-export.outcome.json",
        ),
        (
            OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
            OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
        ),
    ],
)
@pytest.mark.parametrize(
    ("items_only", "raw"),
    [(True, False), (False, False), (True, True), (False, True)],
)
@pytest.mark.parametrize("existing_dataset", [True, False])
def test_diagnostics_fetch_all_guard_writes_outcome_but_retains_empty_dataset(
    tmp_path, output_name, outcome_name, items_only, raw, existing_dataset
):
    output_path = tmp_path / output_name
    outcome_path = tmp_path / outcome_name
    network_scope_path(outcome_path).write_text('{"snapshotSha256":"stale"}')
    old_dataset = b'[{"id":"previous-diagnostic"}]'
    old_scope = b'{"previous":"network-scope"}'
    old_checkpoint = b'[{"id":"previous-checkpoint"}]'
    checkpoint_path = tmp_path / f"{output_path.stem}.partial.json"
    if existing_dataset:
        output_path.write_bytes(old_dataset)
        network_scope_path(output_path).write_bytes(old_scope)
        checkpoint_path.write_bytes(old_checkpoint)
    device = {
        "id": "1111111111111111",
        "role": "router",
        "mlEidIid": "0000000000000000",
    }
    outcome = {
        "items": [],
        "deviceResults": [
            {
                "deviceId": device["id"],
                "role": "router",
                "status": "skipped",
                "skipReasonCode": "unresolved_mesh_local_iid",
                "attempts": 0,
                "mlEidIid": "0000000000000000",
            }
        ],
        "partial": True,
        "clearedDiagnostics": False,
        "inputCount": 1,
        "queriedCount": 1,
        "attemptedCount": 0,
    }
    client = Mock()
    client.list_devices.return_value = [device]

    def fetch_all(_selected, **kwargs):
        kwargs["on_checkpoint"]([], 1, 1, device["id"], "skipped")
        return outcome

    client.fetch_all_devices_diagnostics.side_effect = fetch_all
    command_args = ["diagnostics", "fetch-all", "--no-update-devices"]
    if items_only:
        command_args.append("--items-only")
    args = cli_module.build_parser().parse_args(command_args)
    args.resolved_output_path = str(output_path)

    with patch.object(
        diagnostics_module,
        "emit_rest_command_output",
        side_effect=AssertionError("guarded empty dataset must not be written"),
    ):
        result = diagnostics_module.dispatch_diagnostics(
            client, args, raw_arg=raw, fields=None
        )

    assert result == ([] if items_only else outcome)
    if existing_dataset:
        assert output_path.read_bytes() == old_dataset
        assert network_scope_path(output_path).read_bytes() == old_scope
        assert checkpoint_path.read_bytes() == old_checkpoint
    else:
        assert not output_path.exists()
        assert not network_scope_path(output_path).exists()
        assert not checkpoint_path.exists()
    saved_outcome = json.loads((tmp_path / outcome_name).read_text(encoding="utf-8"))
    assert saved_outcome["deviceResults"][0]["skipReasonCode"] == (
        "unresolved_mesh_local_iid"
    )
    assert saved_outcome["attemptedCount"] == 0
    scope, error = read_network_scope(outcome_path)
    assert error is None
    assert scope is not None
    assert client.fetch_all_devices_diagnostics.call_args.args[0] == [device]


@pytest.mark.parametrize(
    ("outcome_name", "active_network", "operator_network", "expected_network", "provenance"),
    [
        (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
         "1234567890abcdef", "abcdef1234567890", "1234567890abcdef", "observed"),
        (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
         None, "abcdef1234567890", "abcdef1234567890", "operator"),
        (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
         None, None, None, "unknown"),
        ("custom.outcome.json", "1234567890abcdef", None, None, "unknown"),
        ("custom.outcome.json", "1234567890abcdef",
         "abcdef1234567890", "abcdef1234567890", "operator"),
    ],
)
def test_guard_outcome_scope_preserves_observed_operator_and_unknown_provenance(
    tmp_path, monkeypatch, outcome_name, active_network, operator_network,
    expected_network, provenance,
):
    if active_network:
        (tmp_path / OTBR_RESTAPI_DATASET_ACTIVE_FILENAME).write_text(
            json.dumps({"extPanId": active_network})
        )
    if operator_network:
        monkeypatch.setenv(TD_EXT_PAN_ID_ENV_VAR, operator_network)
    else:
        monkeypatch.delenv(TD_EXT_PAN_ID_ENV_VAR, raising=False)
    outcome_path = tmp_path / outcome_name
    diagnostics_module._write_guard_affected_outcome(
        {"partial": True, "deviceResults": []}, outcome_path,
        raw=False, command_name="diagnostics fetch-all",
    )

    scope, error = read_network_scope(outcome_path)
    assert error is None
    assert scope is not None
    assert scope["extPanId"] == expected_network
    assert scope["provenance"] == provenance


def test_guard_outcome_scope_write_failure_is_logged_and_rejects_stale_binding(
    tmp_path, caplog,
):
    outcome_path = tmp_path / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
    diagnostics_module._write_guard_affected_outcome(
        {"partial": False}, outcome_path, raw=False, command_name="diagnostics fetch-all",
    )
    old_scope = network_scope_path(outcome_path).read_bytes()
    caplog.clear()
    with (
        patch("util_data.write_network_scope",
                     side_effect=OSError("scope write failed")),
        caplog.at_level("INFO"),
        pytest.raises(OSError, match="scope write failed"),
    ):
        diagnostics_module._write_guard_affected_outcome(
            {"partial": True}, outcome_path, raw=False, command_name="diagnostics fetch-all",
        )

    assert "event=diagnostic_outcome_write_failed" in caplog.text
    assert "event=diagnostic_outcome_write command=" not in caplog.text
    assert network_scope_path(outcome_path).read_bytes() == old_scope
    assert read_network_scope(outcome_path) == (None, "digest-mismatch")


def test_diagnostics_fetch_all_guard_without_output_path_creates_no_sidecar():
    client = Mock()
    client.list_devices.return_value = [
        {"id": "1111111111111111", "mlEidIid": "0000000000000000"}
    ]
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [
            {
                "skipReasonCode": "unresolved_mesh_local_iid",
                "status": "skipped",
            }
        ],
        "partial": True,
    }
    args = cli_module.build_parser().parse_args(
        ["diagnostics", "fetch-all", "--no-update-devices", "--items-only"]
    )
    args.resolved_output_path = None

    with patch.object(diagnostics_module, "save_json_atomic") as outcome_write:
        assert (
            diagnostics_module.dispatch_diagnostics(
                client, args, raw_arg=False, fields=None
            )
            == []
        )
    outcome_write.assert_not_called()


@pytest.mark.parametrize("command", ["diagnostics", "mesh-diagnostics"])
@pytest.mark.parametrize("items_only", [False, True])
@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("custom_output", [False, True])
def test_standalone_sweep_replaces_old_outcome_and_scope_without_iid_guards(
    tmp_path, command, items_only, raw, custom_output,
):
    output_name = "export.json" if custom_output else f"td-otbr-restapi-{command}-fetch-all.json"
    output_path = tmp_path / output_name
    outcome_path = tmp_path / f"{output_path.stem}.outcome.json"
    outcome_path.write_text('{"partial":true,"completedAt":"2026-09-25T00:00:00Z"}')
    network_scope_path(outcome_path).write_text('{"snapshotSha256":"stale"}')
    outcome = {
        "items": [{"id": "diag-1"}],
        "deviceResults": [{"deviceId": "1111111111111111", "status": "completed"}],
        "partial": False,
        "startedAt": "2026-10-27T16:00:00Z",
        "completedAt": "2026-10-27T16:01:00Z",
    }
    client = Mock()
    client.list_devices.return_value = [{"id": "1111111111111111", "role": "router"}]
    client.fetch_all_devices_diagnostics.return_value = outcome
    client.fetch_mesh_diagnostics_all_devices.side_effect = (
        lambda *_args, **kwargs: outcome["items"] if kwargs.get("items_only") else outcome
    )
    argv = [command, "fetch-all", "--no-update-devices"]
    if items_only:
        argv.append("--items-only")
    args = cli_module.build_parser().parse_args(argv)
    args.resolved_output_path = str(output_path)

    if command == "diagnostics":
        result = diagnostics_module.dispatch_diagnostics(client, args, raw, None)
    else:
        result = mesh_module.dispatch_mesh_diagnostics(client, args, raw)

    assert result == (outcome["items"] if items_only else outcome)
    assert json.loads(outcome_path.read_text()) == outcome
    scope, error = read_network_scope(outcome_path)
    assert error is None and scope is not None
    assert json.loads(output_path.read_text()) == result


def test_diagnostics_fetch_all_guarded_partial_run_writes_items_and_full_outcome(
    tmp_path,
):
    output_path = tmp_path / "diagnostics-export.json"
    client = Mock()
    client.list_devices.return_value = [
        {"id": "1111111111111111", "mlEidIid": "0000000000000000"},
        {"id": "2222222222222222", "mlEidIid": "1234567890abcdef"},
    ]
    outcome = {
        "items": [{"id": "diag-2"}],
        "deviceResults": [
            {
                "deviceId": "1111111111111111",
                "status": "skipped",
                "skipReasonCode": "unresolved_mesh_local_iid",
            },
            {"deviceId": "2222222222222222", "status": "completed", "attempts": 1},
        ],
        "partial": True,
        "attemptedCount": 1,
    }
    client.fetch_all_devices_diagnostics.return_value = outcome
    args = cli_module.build_parser().parse_args(
        ["diagnostics", "fetch-all", "--no-update-devices"]
    )
    args.resolved_output_path = str(output_path)

    diagnostics_module.dispatch_diagnostics(client, args, raw_arg=False, fields=None)

    assert json.loads(output_path.read_text(encoding="utf-8"))["items"] == [
        {"id": "diag-2"}
    ]
    saved_outcome = json.loads(
        (tmp_path / "diagnostics-export.outcome.json").read_text(encoding="utf-8")
    )
    assert saved_outcome["deviceResults"] == outcome["deviceResults"]
    assert saved_outcome["attemptedCount"] == 1


def test_diagnostics_fetch_all_guard_outcome_write_failure_propagates(tmp_path):
    output_path = tmp_path / "diagnostics-export.json"
    client = Mock()
    client.list_devices.return_value = [
        {"id": "1111111111111111", "mlEidIid": "0000000000000000"}
    ]
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [
            {
                "skipReasonCode": "unresolved_mesh_local_iid",
                "status": "skipped",
            }
        ],
        "partial": True,
    }
    args = cli_module.build_parser().parse_args(
        ["diagnostics", "fetch-all", "--no-update-devices"]
    )
    args.resolved_output_path = str(output_path)

    with patch("util_data.save_json_atomic", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            diagnostics_module.dispatch_diagnostics(
                client, args, raw_arg=False, fields=None
            )


@pytest.mark.parametrize(
    "policy_args",
    [
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

    with pytest.raises(OTBRUsageError, match="default/recommended"):
        diagnostics_module.dispatch_diagnostics(client, args, False, None)

    client.list_devices.assert_not_called()


def test_no_fallback_and_no_basic_fallback_keep_mode_aware_initial_pass() -> None:
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }
    args = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--no-update-devices",
            "--no-fallback",
            "--no-basic-fallback",
        ]
    )

    with patch.object(
        diagnostics_module, "emit_rest_command_output", side_effect=lambda value, *_a, **_k: value
    ):
        diagnostics_module.dispatch_diagnostics(client, args, False, None)

    options = client.fetch_all_devices_diagnostics.call_args.kwargs
    assert options["child_collection_policy"] == "mode-aware"
    assert options["children_fetch_fast"] is True
    assert options["children_fetch_detail"] is False
    assert options["child_retry_enabled"] is False
    assert options["include_basic_fallback"] is False


def test_explicit_child_pass_controls_conflict_with_custom_policy_before_discovery() -> None:
    client = Mock()
    args = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--preset",
            "minimal",
            "--children-fetch-fast-no",
        ]
    )

    with pytest.raises(OTBRUsageError, match="Child pass controls"):
        diagnostics_module.dispatch_diagnostics(client, args, False, None)

    client.fetch_device_collection.assert_not_called()
    client.list_devices.assert_not_called()


def test_invalid_child_timing_fails_before_device_discovery() -> None:
    client = Mock()
    args = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--child-task-timeout",
            "30",
            "--child-poll-timeout",
            "30",
        ]
    )

    with pytest.raises(OTBRUsageError, match="poll_timeout must be at least"):
        diagnostics_module.dispatch_diagnostics(client, args, False, None)

    client.fetch_device_collection.assert_not_called()
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


def test_mesh_fetch_all_retains_outcome_and_returns_item_array():
    items = [{"id": "diag-mesh", "extAddress": "router-role", "children": []}]
    client = Mock()
    client.list_devices.return_value = [{"id": "router-role", "role": "router"}]
    client.fetch_mesh_diagnostics_all_devices.return_value = {
        "items": items, "deviceResults": [], "partial": False,
    }
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
    assert client.fetch_mesh_diagnostics_all_devices.call_args.kwargs["items_only"] is False
    assert client.fetch_mesh_diagnostics_all_devices.call_args.kwargs["clear_diagnostics"] is False


def test_mesh_fetch_all_routers_only_selector_remains_accepted():
    args = cli_module.build_parser().parse_args(
        ["mesh-diagnostics", "fetch-all", "--routers-only"]
    )

    assert args.routers_only is True

def test_children_expand_by_rloc_requires_extended_destination_before_discovery():
    client = Mock()
    args = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--children-expand-by-rloc",
            "--destination-type",
            "rloc",
        ]
    )

    with pytest.raises(OTBRUsageError, match="--children-expand-by-rloc"):
        diagnostics_module.dispatch_diagnostics(
            client, args, raw_arg=False, fields=None
        )

    client.fetch_device_collection.assert_not_called()
    client.list_devices.assert_not_called()
    client.fetch_all_devices_diagnostics.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_children_expand_by_rloc_is_forwarded_only_when_enabled(enabled):
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }
    command = ["--no-progress", "diagnostics", "fetch-all", "--no-update-devices"]
    if enabled:
        command.append("--children-expand-by-rloc")
    args = cli_module.build_parser().parse_args(command)
    args.resolved_output_path = None

    diagnostics_module.dispatch_diagnostics(client, args, raw_arg=False, fields=None)

    kwargs = client.fetch_all_devices_diagnostics.call_args.kwargs
    if enabled:
        assert kwargs["children_expand_by_rloc"] is True
    else:
        assert "children_expand_by_rloc" not in kwargs


def _incomplete_expansion_outcome(items):
    return {
        "items": items,
        "deviceResults": [],
        "partial": True,
        "clearedDiagnostics": False,
        "inputCount": 0,
        "queriedCount": 0,
        "attemptedCount": 0,
        "childrenExpansion": {
            "enabled": True,
            "partial": True,
            "parentCount": 0,
            "targetCount": 1,
            "attemptedCount": 1,
            "completedCount": 0,
            "coveredCount": 0,
            "results": [
                {
                    "destination": "00382a",
                    "destinationType": "rloc",
                    "status": "failed",
                }
            ],
            "issues": [],
        },
    }


@pytest.mark.parametrize(
    ("output_name", "outcome_name"),
    [
        ("diagnostics-export.json", "diagnostics-export.outcome.json"),
        (
            OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
            OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
        ),
    ],
)
@pytest.mark.parametrize(
    ("items_only", "raw"),
    [(True, False), (False, False), (True, True), (False, True)],
)
def test_incomplete_empty_rloc_expansion_retains_prior_dataset(
    tmp_path, output_name, outcome_name, items_only, raw
):
    output_path = tmp_path / output_name
    checkpoint_path = tmp_path / f"{output_path.stem}.partial.json"
    old_dataset = b'[{"id":"previous-diagnostic"}]'
    old_scope = b'{"previous":"network-scope"}'
    old_checkpoint = b'[{"id":"previous-checkpoint"}]'
    output_path.write_bytes(old_dataset)
    network_scope_path(output_path).write_bytes(old_scope)
    checkpoint_path.write_bytes(old_checkpoint)
    outcome = _incomplete_expansion_outcome([])
    client = Mock()
    client.list_devices.return_value = []

    def fetch_all(_selected, **kwargs):
        kwargs["on_checkpoint"]([], 1, 1, "rloc:00382a", "failed")
        return outcome

    client.fetch_all_devices_diagnostics.side_effect = fetch_all
    command = [
        "diagnostics",
        "fetch-all",
        "--no-update-devices",
        "--children-expand-by-rloc",
    ]
    if items_only:
        command.append("--items-only")
    args = cli_module.build_parser().parse_args(command)
    args.resolved_output_path = str(output_path)

    with patch.object(
        diagnostics_module,
        "emit_rest_command_output",
        side_effect=AssertionError("incomplete empty expansion must not be written"),
    ):
        diagnostics_module.dispatch_diagnostics(client, args, raw_arg=raw, fields=None)

    assert output_path.read_bytes() == old_dataset
    assert network_scope_path(output_path).read_bytes() == old_scope
    assert checkpoint_path.read_bytes() == old_checkpoint
    saved = json.loads((tmp_path / outcome_name).read_text(encoding="utf-8"))
    assert saved["childrenExpansion"]["results"][0]["status"] == "failed"
    assert saved["childrenExpansion"]["partial"] is True


def test_usable_base_snapshot_is_published_when_rloc_children_fail(tmp_path):
    output_path = tmp_path / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME
    parent = {"id": "diag-parent", "extAddress": "9af0b8a484b741ab", "rloc16": "0x3800"}
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_all_devices_diagnostics.return_value = _incomplete_expansion_outcome(
        [parent]
    )
    args = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--no-update-devices",
            "--no-enrich-mac-counters",
            "--children-expand-by-rloc",
            "--items-only",
        ]
    )
    args.resolved_output_path = str(output_path)

    with patch.object(diagnostics_module, "emit_rest_command_output") as emit:
        diagnostics_module.dispatch_diagnostics(client, args, raw_arg=False, fields=None)

    emit.assert_called_once()
    assert emit.call_args.args[0][0]["extAddress"] == parent["extAddress"]
    saved = json.loads(
        (tmp_path / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert saved["partial"] is True


def test_incomplete_rloc_expansion_without_output_path_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_all_devices_diagnostics.return_value = _incomplete_expansion_outcome([])
    args = cli_module.build_parser().parse_args(
        ["diagnostics", "fetch-all", "--no-update-devices", "--children-expand-by-rloc"]
    )
    args.resolved_output_path = None

    with patch.object(diagnostics_module, "emit_rest_command_output") as emit:
        diagnostics_module.dispatch_diagnostics(client, args, raw_arg=False, fields=None)

    emit.assert_not_called()
    assert list(tmp_path.iterdir()) == []
