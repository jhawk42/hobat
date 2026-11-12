import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import logging

import pytest

import otbr_restapi_actions as actions_module
import otbr_restapi_devices as devices_module
import otbr_restapi_diagnostics as diagnostics_module
import otbr_restapi_mesh_diagnostics as mesh_module
import otbr_restapi_node as node_module
import otbr_restapi_cli as cli_module
from otbr_restapi_util import OTBRUsageError, emit_rest_command_output
from otbr_restapi_util import _RAW_UNSET
from otbr_restapi_util import rest_payload_record_count, emit_rest_observed_output
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


def test_devices_clear_dispatch_rejects_missing_confirmation():
    client = Mock()
    args = SimpleNamespace(devices_command="clear", yes=False)
    with pytest.raises(OTBRUsageError, match="requires --yes"):
        devices_module.dispatch_devices(client, args, False, None)
    assert client.mock_calls == []


def test_mesh_response_flag_rejects_children_before_requests():
    client = Mock()
    args = SimpleNamespace(mesh_diag_command="fetch-all", types=None, poll_timeout=20,
                           poll_interval=2, destination_type="extended", task_timeout=15,
                           routers_only=False, diagnostic_response_fallback=True)
    with pytest.raises(OTBRUsageError, match="requires --routers-only"):
        mesh_module.dispatch_mesh_diagnostics(client, args, False)
    assert client.mock_calls == []


@pytest.mark.parametrize("kind", ["diagnostics", "mesh-diagnostics"])
@pytest.mark.parametrize("case", ["saved", "retained_previous", "not_requested", "outcome_failed", "final_failed"])
def test_rest_batch_write_dispositions(tmp_path, monkeypatch, caplog, kind, case):
    import logging
    import util_data

    client = Mock()
    client.list_devices.return_value = []
    outcome = {"items": [], "deviceResults": [], "partial": case == "retained_previous"}
    client.fetch_all_devices_diagnostics.return_value = outcome
    client.fetch_mesh_diagnostics_all_devices.return_value = outcome
    args = cli_module.build_parser().parse_args([
        "--no-progress", kind, "fetch-all", "--no-update-devices",
    ])
    path = None if case == "not_requested" else tmp_path / "output.json"
    args.resolved_output_path = path
    module = diagnostics_module if kind == "diagnostics" else mesh_module
    dispatch = lambda: (
        diagnostics_module.dispatch_diagnostics(client, args, False, None)
        if kind == "diagnostics" else mesh_module.dispatch_mesh_diagnostics(client, args, False)
    )
    writer_name = "_write_guard_affected_outcome" if kind == "diagnostics" else "write_rest_collection_outcome"
    if case == "outcome_failed":
        monkeypatch.setattr(module, writer_name, Mock(side_effect=OSError("disk full")))
    if case == "final_failed":
        monkeypatch.setattr(util_data, "save_final_json", Mock(side_effect=OSError("disk full")))
    with caplog.at_level(logging.INFO):
        if case in {"outcome_failed", "final_failed"}:
            with pytest.raises(OSError):
                dispatch()
        else:
            dispatch()
    events = [r.message for r in caplog.records if r.message.startswith('event="write"')]
    if case == "outcome_failed":
        assert any('stage="outcome"' in e and 'disposition="failed"' in e for e in events)
        assert not any('stage="final"' in e for e in events)
    else:
        expected = "failed" if case == "final_failed" else case
        assert any('stage="final"' in e and f'disposition="{expected}"' in e for e in events)
        assert any('stage="outcome"' in e and (
            'disposition="not_requested"' if case == "not_requested" else 'disposition="saved"'
        ) in e for e in events)


@pytest.mark.parametrize("kind", ["diagnostics", "mesh-diagnostics"])
def test_final_companion_failure_is_not_reported_saved(tmp_path, monkeypatch, caplog, kind):
    import logging
    import util_data

    client = Mock()
    client.list_devices.return_value = []
    outcome = {"items": [{"id": "one"}], "deviceResults": [], "partial": False}
    client.fetch_all_devices_diagnostics.return_value = outcome
    client.fetch_mesh_diagnostics_all_devices.return_value = outcome
    args = cli_module.build_parser().parse_args([
        "--no-progress", kind, "fetch-all", "--no-update-devices", "--items-only",
    ])
    args.resolved_output_path = tmp_path / "td-otbr-restapi-test.json"
    original = util_data.write_network_scope
    calls = []

    def write_scope(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 2:
            raise OSError("scope write failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(util_data, "write_network_scope", write_scope)
    with caplog.at_level(logging.INFO), pytest.raises(OSError):
        if kind == "diagnostics":
            diagnostics_module.dispatch_diagnostics(client, args, False, None)
        else:
            mesh_module.dispatch_mesh_diagnostics(client, args, False)
    events = [r.message for r in caplog.records if r.message.startswith('event="write"')]
    assert args.resolved_output_path.exists()
    assert any('stage="outcome"' in e and 'disposition="saved"' in e for e in events)
    assert any('stage="final"' in e and 'disposition="failed"' in e for e in events)
    assert not any('stage="final"' in e and 'disposition="saved"' in e for e in events)


def test_responsiveness_progress_has_independent_fixed_population(monkeypatch, capsys, caplog):
    import logging

    client = Mock()
    client.get_active_dataset.return_value = {"extPanId": "123456789abcdef0"}
    outcome = {"deviceResults": [
        {"deviceId": "1111111111111111", "status": "completed"},
        {"deviceId": "2222222222222222", "status": "failed", "attemptErrors": []},
        {"deviceId": "3333333333333333", "status": "failed", "attemptErrors": []},
    ]}
    with caplog.at_level(logging.INFO):
        mesh_module._attach_responsiveness(
            client, outcome, [], {"extPanId": "123456789abcdef0"}, [], {}, [], None,
            "extended", progress_enabled=True,
        )
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 2
    assert all('stage="responsiveness"' in line and "total=2" in line for line in lines)
    assert "current=1" in lines[0] and "current=2" in lines[1]
    assert 'targets=2 checks=0' in caplog.text
    client.fetch_device_diagnostics.assert_not_called()


@pytest.mark.parametrize("kind", ["diagnostics", "mesh-diagnostics"])
@pytest.mark.parametrize("no_progress", [False, True])
def test_items_only_stdout_keeps_existing_payload_and_status(monkeypatch, capsys, kind, no_progress):
    client = Mock()
    client.list_devices.return_value = [{"id": "1111111111111111", "role": "router"}]

    def sweep(_devices, **kwargs):
        if kwargs["on_progress"]:
            kwargs["on_progress"](1, 1, "1111111111111111", 0.1, "completed")
        return {"items": [{"id": "diagnostic"}], "deviceResults": [], "partial": False}

    client.fetch_all_devices_diagnostics.side_effect = sweep
    client.fetch_mesh_diagnostics_all_devices.side_effect = sweep
    monkeypatch.setattr(cli_module, "build_client", lambda _args: client)
    monkeypatch.setattr(cli_module, "_auto_output_path", lambda *_args: None)
    args = (["--no-progress"] if no_progress else []) + [
        kind, "fetch-all", "--no-update-devices", "--items-only",
    ]
    assert cli_module.main(args) == 0
    output = capsys.readouterr()
    payload, end = json.JSONDecoder().raw_decode(output.out)
    assert payload == [{"id": "diagnostic"}]
    assert output.out[end:].strip() == "Output written to stdout"
    assert 'event="target_progress"' not in output.out
    assert ('event="target_progress"' in output.err) is not no_progress


@pytest.mark.parametrize("case,answered,not_provided,guard", [
    ("valid", 18, 1, True),
    ("no-answered-router", 0, 1, False),
    ("scope-changed", 18, 0, True),
    ("tampered-binding", 18, 0, True),
    ("no-response", 18, 0, True),
    ("children-uncovered", 18, 0, True),
])
def test_mesh_coverage_events_use_qualification_contract(tmp_path, monkeypatch, caplog, case, answered, not_provided, guard):
    import logging
    from test_td_unified_dataset import _seed_rest_mesh_response

    _seed_rest_mesh_response(tmp_path, case)
    original = json.loads((tmp_path / "td-otbr-restapi-mesh-diagnostics-fetch-all.outcome.json").read_text())
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_mesh_diagnostics_all_devices.return_value = original
    monkeypatch.setattr(mesh_module, "_observe_scope", lambda _: {"extPanId": "1234567890abcdef"})
    monkeypatch.setattr(mesh_module, "_attach_responsiveness", lambda *_args, **_kwargs: None)
    monkeypatch.setenv(TD_EXT_PAN_ID_ENV_VAR, "1234567890abcdef")
    args = cli_module.build_parser().parse_args([
        "--no-progress", "mesh-diagnostics", "fetch-all", "--no-update-devices",
        "--diagnostic-response-fallback", "--items-only",
    ])
    args.resolved_output_path = tmp_path / "td-otbr-restapi-test-mesh.json"
    with caplog.at_level(logging.INFO):
        mesh_module.dispatch_mesh_diagnostics(client, args, False)
    coverage = next(r.message for r in caplog.records if r.message.startswith('event="coverage"'))
    if case == "scope-changed":
        assert 'availability="unavailable"' in coverage
        client.fetch_device_diagnostics.assert_not_called()
        return
    assert 'availability="available"' in coverage
    assert f"answered={answered}" in coverage
    assert f"not_provided={not_provided}" in coverage
    assert f"guard_passed={str(guard).lower()}" in coverage
    client.fetch_device_diagnostics.assert_not_called()


@pytest.mark.parametrize("error", [
        OSError("networkKey=sentinel-secret\nforged-event"),
        ValueError("password=sentinel-secret"),
])
def test_mesh_qualification_errors_are_visible_and_sanitized(tmp_path, monkeypatch, caplog, error):
    import logging
    import td_unified_dataset

    def fail(*_args):
        raise error

    monkeypatch.setattr(td_unified_dataset, "_recheck", fail)
    with caplog.at_level(logging.INFO):
        mesh_module._log_qualification({}, tmp_path / "mesh.json", tmp_path / "outcome.json", [], {}, [])
    event = next(r.message for r in caplog.records if r.message.startswith('event="coverage"'))
    assert 'availability="unavailable"' in event
    assert 'reason="qualification_error"' in event
    assert f'error_type="{type(error).__name__}"' in event
    assert "sentinel-secret" not in caplog.text
    assert "forged-event" not in caplog.text


@pytest.mark.parametrize("items_only", [False, True])
def test_mesh_raw_nonempty_final_preserves_existing_normalized_write(tmp_path, items_only):
    from td_json_key_normalizer import convert_keys_to_camel_case

    raw_item = {"data": {"id": "mesh-1", "attributes": {"some_raw_field": "value"}}}
    outcome = {"items": [raw_item], "deviceResults": [], "partial": False}
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_mesh_diagnostics_all_devices.return_value = outcome
    args = cli_module.build_parser().parse_args([
        "--no-progress", "mesh-diagnostics", "fetch-all", "--no-update-devices",
        *(["--items-only"] if items_only else []),
    ])
    args.resolved_output_path = tmp_path / "mesh.json"
    payload = outcome["items"] if items_only else outcome
    assert mesh_module.dispatch_mesh_diagnostics(client, args, True) == payload
    assert client.fetch_mesh_diagnostics_all_devices.call_args.kwargs["raw"] is True
    assert json.loads(args.resolved_output_path.read_text()) == convert_keys_to_camel_case(payload)
    assert json.loads((tmp_path / "mesh.outcome.json").read_text()) == outcome
@pytest.mark.parametrize("enabled", [False, True])
def test_mesh_response_reuses_destination_and_preserves_raw_mesh(tmp_path, monkeypatch, enabled):
    from datetime import datetime, timezone
    from copy import deepcopy
    address = "1111111111111111"
    client = Mock()
    client.get_active_dataset.return_value = {"extPanId": "123456789abcdef0", "networkKey": "do-not-retain"}
    client.list_devices.return_value = [{"id": address, "extAddress": address, "role": "router"}]
    client.fetch_device_diagnostics.side_effect = lambda *_args, **_kwargs: {
        "action": {"id": "new-action", "status": "completed", "relationships": {"result": {"data": {"id": "new-result", "type": "diagnostics"}}}},
        "item": {"id": "new-result", "type": "networkDiagnostics", "created": datetime.now(timezone.utc).isoformat(), "extAddress": address},
    }
    original = {}
    def sweep(*_args, **_kwargs):
        now = datetime.now(timezone.utc).isoformat()
        original.update(items=[], partial=True, startedAt=now, completedAt=now, queriedCount=1,
                        deviceResults=[{"deviceId": address, "status": "failed", "attemptErrors": [{"type": "OTBRActionFailedError", "actionId": "old-action", "actionStatus": "stopped"}]}])
        return deepcopy(original)
    client.fetch_mesh_diagnostics_all_devices.side_effect = sweep
    witness_time = "2026-11-05T00:00:00Z"
    table = {"extAddress": address, "diagnosticId": "old-diag", "created": witness_time, "childTable": [], "resolvedChildren": []}
    monkeypatch.setattr(mesh_module, "_capture_child_witness", lambda *_args: ([table], {"witness": "a" * 64}, []))
    monkeypatch.setattr(mesh_module, "select_child_witness", lambda *_args: ({"diagnosticId": "old-diag", "created": witness_time, "extAddress": address}, None))
    output = tmp_path / "mesh.json"
    args = SimpleNamespace(mesh_diag_command="fetch-all", types=None, poll_timeout=20, poll_interval=2,
                           destination_type="extended", task_timeout=15, routers_only=True,
                           no_update_devices=True, diagnostic_response_fallback=enabled,
                           no_progress=True, no_fallback=True, items_only=True, resolved_output_path=output)
    assert mesh_module.dispatch_mesh_diagnostics(client, args, False) == []
    saved = json.loads(output.with_suffix(".outcome.json").read_text())
    for key, value in original.items():
        assert saved[key] == value
    assert client.fetch_mesh_diagnostics_all_devices.call_args.kwargs["progressive_fallback"] is False
    assert client.fetch_device_diagnostics.call_count == int(enabled)
    assert client.get_active_dataset.call_count == 2 * int(enabled)
    client.get_device.assert_not_called()
    if enabled:
        call = client.fetch_device_diagnostics.call_args
        assert call.args == (address,)
        assert call.kwargs == {"types": ["extAddress", "rloc16", "mode", "ipv6Addresses"], "destination_type": "extended", "task_timeout": 15, "poll_interval": 2.0, "poll_timeout": 20.0, "return_context": True, "raw": False}
        assert saved["meshResponsiveness"]["targets"][0]["check"]["status"] == "response"
        assert "do-not-retain" not in json.dumps(saved)
    else:
        assert "meshResponsiveness" not in saved


@pytest.mark.parametrize("case", ["timeout", "connection", "malformed", "cancelled", "scope-changed", "changed-witness", "missing-witness"])
def test_mesh_response_failure_boundaries_do_not_retry_or_rewrite(tmp_path, monkeypatch, case):
    from copy import deepcopy
    from otbr_restapi_util import OTBRActionTimeoutError, OTBRConnectionError
    from td_restapi_mesh_evidence import POLICY
    from td_unified_dataset import UnifiedDatasetError
    address = "1111111111111111"
    original = {"items": [], "partial": True, "deviceResults": [{"deviceId": address, "status": "failed", "attemptErrors": [{"type": "OTBRActionFailedError", "actionId": "mesh-stopped", "actionStatus": "stopped"}]}]}
    client = Mock()
    client.get_active_dataset.return_value = {"extPanId": "123456789abcdef0"}
    context = {"action": {"id": "new-action", "status": "completed", "relationships": {"result": {"data": {"id": "new-result"}}}}, "item": {"id": "new-result", "type": "networkDiagnostics", "extAddress": address, "created": "2026-11-05T00:00:00Z"}}
    client.fetch_device_diagnostics.return_value = context
    if case == "timeout":
        client.fetch_device_diagnostics.side_effect = OTBRActionTimeoutError("timeout", action_id="new-action", status="running")
    elif case == "connection":
        client.fetch_device_diagnostics.side_effect = OTBRConnectionError("unavailable")
    elif case == "cancelled":
        client.fetch_device_diagnostics.side_effect = KeyboardInterrupt()
    elif case == "malformed":
        client.fetch_device_diagnostics.return_value = {}
    elif case == "scope-changed":
        client.get_active_dataset.return_value = {"extPanId": "ffffffffffffffff"}
    monkeypatch.setattr(mesh_module, "_utc_now", lambda: "2026-11-05T00:00:00Z")
    monkeypatch.setattr(mesh_module, "select_child_witness", lambda *_args: (None, "witness-missing") if case == "missing-witness" else ({"diagnosticId": "old", "created": "2026-11-05T00:00:00Z", "extAddress": address}, None))
    captured = []
    if case == "changed-witness":
        captured = [SimpleNamespace(content=b"{}")]
        def changed(*_args):
            raise UnifiedDatasetError("changed original")
        monkeypatch.setattr("td_unified_dataset._recheck", changed)
    outcome = deepcopy(original)
    def attach():
        mesh_module._attach_responsiveness(client, outcome, [{"id": address, "extAddress": address, "role": "router"}], {"extPanId": "123456789abcdef0"}, [], {"witness": "a" * 64}, captured, tmp_path / "mesh.json", "extended")
    if case == "cancelled":
        with pytest.raises(KeyboardInterrupt):
            attach()
        assert "meshResponsiveness" not in outcome
    else:
        attach()
        evidence = outcome["meshResponsiveness"]
        check = evidence["targets"][0]["check"]
        if case in {"timeout", "connection"}:
            assert check["status"] == "no-response"
        elif case == "malformed":
            assert check["status"] == "invalid-response"
        elif case == "scope-changed":
            assert check["reasonCode"] == "scope-changed"
        elif case == "changed-witness":
            assert check["reasonCode"] == "witness-binding-mismatch"
            assert evidence["witnessBindings"] == {}
        elif case == "missing-witness":
            assert check["status"] == "not-attempted"
        assert evidence["policy"] == POLICY
    assert client.fetch_device_diagnostics.call_count == int(case != "missing-witness")
    assert {key: outcome[key] for key in original} == original
    client.get_device.assert_not_called()
    client.fetch_device_collection.assert_not_called()


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

@pytest.mark.parametrize("flag", [[], ["--children-expand-by-rloc"]])
@pytest.mark.parametrize("destination", ["rloc", "mleid"])
@pytest.mark.parametrize("internal", [False, True])
def test_children_expand_by_rloc_requires_extended_destination_before_discovery(
    flag, destination, internal
):
    client = Mock()
    args = cli_module.build_parser().parse_args(
        [
            "diagnostics",
            "fetch-all",
            "--destination-type",
            destination,
            *flag,
        ],
    )
    if internal:
        del args.children_expand_by_rloc

    with pytest.raises(OTBRUsageError, match="--no-children-expand-by-rloc"):
        diagnostics_module.dispatch_diagnostics(
            client, args, raw_arg=False, fields=None
        )

    assert client.mock_calls == []


@pytest.mark.parametrize(
    ("flag", "enabled", "destination", "internal"),
    [
        ([], True, "extended", False),
        (["--children-expand-by-rloc"], True, "extended", False),
        (["--no-children-expand-by-rloc"], False, "extended", False),
        (["--no-children-expand-by-rloc"], False, "rloc", False),
        (["--no-children-expand-by-rloc"], False, "mleid", False),
        ([], True, "extended", True),
    ],
)
def test_children_expand_by_rloc_resolved_and_forwarded(
    flag, enabled, destination, internal
):
    client = Mock()
    client.list_devices.return_value = []
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }
    command = [
        "--no-progress", "diagnostics", "fetch-all", "--no-update-devices",
        "--destination-type", destination, *flag,
    ]
    args = cli_module.build_parser().parse_args(command)
    if internal:
        del args.children_expand_by_rloc
    args.resolved_output_path = None

    diagnostics_module.dispatch_diagnostics(client, args, raw_arg=False, fields=None)

    kwargs = client.fetch_all_devices_diagnostics.call_args.kwargs
    assert kwargs["children_expand_by_rloc"] is enabled
    assert kwargs["destination_type"] == destination


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


@pytest.mark.parametrize(
    ("payload", "single", "count"),
    [
        ([{}, {}], False, 2), ({"items": []}, False, 0),
        ({"items": [{}, {}]}, False, 2), ({"data": [{}]}, False, 1),
        ({"id": "device"}, True, 1), ({"data": {"id": "device"}}, True, 1),
        ({"metadata": [1, 2]}, False, "unavailable"),
        ({"metadata": [1, 2]}, True, "unavailable"),
        ({"data": {"unknown": []}}, True, "unavailable"),
        ("text", True, "unavailable"), ({}, True, "unavailable"),
    ],
)
def test_rest_observed_record_count(payload, single, count):
    assert rest_payload_record_count(payload, single=single) == count


def test_rest_observed_no_path_and_text_callback(tmp_path, caplog, capsys):
    caplog.set_level(logging.INFO)
    callbacks = []
    assert emit_rest_observed_output(
        [{"id": 1}], None, command="devices list", stage="final"
    ) == [{"id": 1}]
    assert 'disposition="not_requested"' in caplog.text
    path = tmp_path / "state.txt"
    assert emit_rest_command_output("hello", path, plain_text=True, on_write=callbacks.append) == "hello"
    assert callbacks == [True]
    assert path.read_text() == "hello\n"
    assert capsys.readouterr().out == ""


def test_text_callback_not_called_on_save_failure(tmp_path, monkeypatch):
    import util_data

    callback = Mock()
    monkeypatch.setattr(util_data, "save_text_atomic", Mock(side_effect=OSError("failure")))
    with pytest.raises(OSError):
        emit_rest_command_output("hello", tmp_path / "state.txt",
                                 plain_text=True, on_write=callback)
    callback.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "raw", "count"),
    [([{"id": "a"}], False, 1), ({"items": []}, False, 0),
     ({"data": [{"id": "a"}, {"id": "b"}]}, True, 2),
     ({"unknown": [{"id": "a"}]}, True, "unavailable")],
)
def test_devices_list_reports_actual_population(payload, raw, count, caplog):
    caplog.set_level(logging.INFO)
    client = Mock()
    client.list_devices.return_value = payload
    args = SimpleNamespace(devices_command="list", with_meta=False, resolved_output_path=None)
    assert devices_module.dispatch_devices(client, args, raw, None) == payload
    expected = f'records="{count}"' if isinstance(count, str) else f"records={count}"
    assert expected in caplog.text
    assert 'disposition="not_requested"' in caplog.text


def test_rest_observed_failed_serialization_and_scope(tmp_path, monkeypatch, caplog):
    import util_data

    caplog.set_level(logging.INFO)
    with pytest.raises(TypeError):
        emit_rest_observed_output([{"bad": object()}], tmp_path / "bad.json",
                                  command="devices list", stage="final")
    assert 'records=1 disposition="failed"' in caplog.text
    caplog.clear()
    monkeypatch.setattr(util_data, "write_network_scope", Mock(side_effect=OSError("scope failure")))
    path = tmp_path / "td-otbr-restapi-devices.json"
    with pytest.raises(OSError, match="scope failure"):
        emit_rest_observed_output([{"id": "one"}], path,
                                  command="devices list", stage="final")
    assert json.loads(path.read_text()) == [{"id": "one"}]
    assert 'disposition="failed"' in caplog.text
    assert 'disposition="saved"' not in caplog.text


@pytest.mark.parametrize("items,expected", [([{"id": "a"}, {"id": "b"}], "written"), ([], "skipped_unusable")])
def test_devices_checkpoint_reports_structured_count(tmp_path, caplog, items, expected):
    caplog.set_level(logging.INFO)
    devices_module._write_checkpoint_best_effort(
        {"partial": True, "items": items}, tmp_path / "checkpoint.json"
    )
    assert f'records={len(items)} disposition="{expected}"' in caplog.text


def test_devices_checkpoint_failure_does_not_prevent_final(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(devices_module, "save_checkpoint_json", Mock(side_effect=OSError("failed")))
    payload = {"partial": True, "items": [{"id": "a"}]}
    client = Mock()
    client.fetch_device_collection.return_value = payload
    args = SimpleNamespace(
        devices_command="fetch", device_count=1, max_age=None, max_retries=1,
        task_timeout=1, poll_interval=1, poll_timeout=1, structured_outcome=True,
        resolved_output_path=tmp_path / "devices.json",
    )
    assert devices_module.dispatch_devices(client, args, False, None) == payload
    assert json.loads(args.resolved_output_path.read_text()) == payload
    assert 'records=1 disposition="failed"' in caplog.text
    assert 'records=1 disposition="saved"' in caplog.text


def test_devices_checkpoint_failure_warning_escapes_and_redacts(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        devices_module, "save_checkpoint_json",
        Mock(side_effect=OSError("networkKey=secret-sentinel\nforged-event")),
    )
    devices_module._write_checkpoint_best_effort(
        {"partial": True, "items": [{"id": "a"}]}, tmp_path / "checkpoint.json"
    )
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "secret-sentinel" not in caplog.text
    assert "\\nforged-event" in warnings[0].message
    assert "\n" not in warnings[0].message
    assert 'error_type="OSError"' in warnings[0].message
    assert "action=continue_best_effort" in warnings[0].message


def test_devices_retains_previous_on_empty_partial(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    path = tmp_path / "devices.json"
    path.write_text('["previous"]')
    client = Mock()
    client.fetch_device_collection.return_value = {"partial": True, "items": []}
    args = SimpleNamespace(
        devices_command="fetch", device_count=1, max_age=None, max_retries=1,
        task_timeout=1, poll_interval=1, poll_timeout=1, structured_outcome=True,
        resolved_output_path=path,
    )
    devices_module.dispatch_devices(client, args, False, None)
    assert json.loads(path.read_text()) == ["previous"]
    assert 'records=0 disposition="retained_previous"' in caplog.text


def test_action_accepted_before_write_failure_without_repeat(tmp_path, monkeypatch, caplog):
    import util_data

    caplog.set_level(logging.INFO)
    client = Mock()
    client.enqueue_add_thread_device_task.return_value = {"id": "a", "status": "queued", "accepted": True}
    monkeypatch.setattr(util_data, "save_final_json", Mock(side_effect=OSError("write failed")))
    args = SimpleNamespace(
        actions_command="enqueue", enqueue_type="add-thread-device",
        pskd="secret-sentinel", eui=None, discerner=None, joiner_id=None, timeout=1,
        resolved_output_path=tmp_path / "action.json",
    )
    with pytest.raises(OSError):
        actions_module.dispatch_actions(client, args, False, None, False)
    client.enqueue_add_thread_device_task.assert_called_once()
    assert 'state="returned"' in caplog.text
    assert 'action_state="queued"' in caplog.text
    assert 'accepted=true' in caplog.text
    assert 'disposition="failed"' in caplog.text
    assert "secret-sentinel" not in caplog.text


@pytest.mark.parametrize(
    ("args", "method", "command"),
    [
        ({"node_command": "get"}, "get_node", "node get"),
        ({"node_command": "state", "state_command": "get"}, "get_node_state", "node state get"),
        ({"node_command": "state", "state_command": "set", "value": "disabled"}, "set_node_state", "node state set"),
        ({"node_command": "dataset", "dataset_kind": "active", "dataset_command": "get", "text": False},
         "get_active_dataset", "node dataset active get"),
        ({"node_command": "dataset", "dataset_kind": "active", "dataset_command": "set",
          "json": '{"networkKey":"secret-sentinel"}', "json_file": None, "text": None, "text_file": None},
         "set_active_dataset", "node dataset active set"),
    ],
)
def test_node_operation_and_no_output_events(args, method, command, caplog, capsys):
    caplog.set_level(logging.INFO)
    client = Mock()
    getattr(client, method).return_value = {"id": "node", "networkKey": "secret-sentinel"}
    args = SimpleNamespace(**args, resolved_output_path=None)
    node_module.dispatch_node(client, args, True, None)
    getattr(client, method).assert_called_once()
    assert f'command="{command}"' in caplog.text
    assert 'event="operation_end"' in caplog.text and 'state="returned"' in caplog.text
    assert 'disposition="not_requested"' in caplog.text
    assert "secret-sentinel" not in caplog.text
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("wait", [False, True])
def test_action_wait_preserves_existing_calls_and_observed_state(wait, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    client = Mock()
    client.enqueue_get_network_diagnostic_task.return_value = {"id": "a", "status": "pending"}
    client.run_action.return_value = {
        "status": "completed", "relationships": {"result": {"data": {"id": "d"}}}
    }
    client.get_diagnostic.return_value = {"id": "d"}
    monkeypatch.setattr(actions_module, "resolve_types", lambda _: [1])
    args = SimpleNamespace(
        actions_command="enqueue", enqueue_type="get-network-diagnostic",
        destination="a", destination_type="extAddress", timeout=10,
        wait=wait, poll_interval=1, poll_timeout=2, resolved_output_path=None,
    )
    result = actions_module.dispatch_actions(client, args, False, None, False)
    if wait:
        assert result == {"id": "d"}
        client.run_action.assert_called_once()
        client.get_diagnostic.assert_called_once_with("d", raw=False)
        assert 'action_state="completed"' in caplog.text
    else:
        assert result == {"id": "a", "status": "pending"}
        client.enqueue_get_network_diagnostic_task.assert_called_once()
        client.run_action.assert_not_called()
        client.get_diagnostic.assert_not_called()
        assert 'action_state="pending"' in caplog.text
    assert 'state="returned"' in caplog.text
    assert 'disposition="not_requested"' in caplog.text


@pytest.mark.parametrize("operation", ["list", "get"])
def test_action_list_and_get_observed(operation, caplog):
    caplog.set_level(logging.INFO)
    client = Mock()
    client.list_actions.return_value = [{"id": "a"}]
    client.get_action.return_value = {"id": "a", "status": "active"}
    args = SimpleNamespace(actions_command=operation, action_id="a", with_meta=False,
                           resolved_output_path=None)
    actions_module.dispatch_actions(client, args, True, None, True)
    assert f'command="actions {operation}"' in caplog.text
    assert 'state="returned"' in caplog.text
    assert 'records=1 disposition="not_requested"' in caplog.text


def test_node_operation_failure_has_no_write_event(caplog):
    caplog.set_level(logging.INFO)
    client = Mock()
    client.get_node_state.side_effect = ValueError("failure")
    args = SimpleNamespace(node_command="state", state_command="get", resolved_output_path=None)
    with pytest.raises(ValueError):
        node_module.dispatch_node(client, args, False, None)
    assert 'event="operation_end"' in caplog.text and 'state="raised"' in caplog.text
    assert 'event="write"' not in caplog.text
