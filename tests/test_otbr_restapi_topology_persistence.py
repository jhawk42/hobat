from __future__ import annotations

import json
import logging
from pathlib import Path
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
from util_data import create_checkpoint_filename, network_scope_path


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

    def save(_payload, path, _logger, *, on_write):
        events.append(f"save:{path.name}")
        on_write(True)

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

    def save(_payload, path, _logger, *, on_write):
        saved_paths.append(path.name)
        on_write(True)

    with patch.object(
        topology_module,
        "emit_rest_payload_output",
        side_effect=save,
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


def test_topology_uses_refreshed_roster_mode_for_diagnostics(tmp_path):
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "topology",
            "--skip-devices",
            "--skip-mesh-diagnostics",
            "--no-enrich-mac-counters",
        ]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    client.list_devices.return_value = [
        {
            "id": "1111111111111111",
            "role": "child",
            "mode": {"fullThreadDevice": True, "device": "FTD"},
        }
    ]
    refreshed_roster = [
        {
            "id": "1111111111111111",
            "role": "child",
            "mode": {"fullThreadDevice": False, "device": "MTD"},
            "mlEidIid": "0000000000000000",
        }
    ]
    client.fetch_device_collection.return_value = refreshed_roster
    client.fetch_all_devices_diagnostics.return_value = {
        "items": [],
        "deviceResults": [],
        "partial": False,
    }

    with patch.object(
        topology_module,
        "emit_rest_payload_output",
        wraps=topology_module.emit_rest_payload_output,
    ):
        topology_module.dispatch_topology(client, args, raw_arg=False)

    selected_devices = client.fetch_all_devices_diagnostics.call_args.args[0]
    assert selected_devices == refreshed_roster
    assert selected_devices[0]["mode"]["device"] == "MTD"
    assert (
        client.fetch_all_devices_diagnostics.call_args.kwargs[
            "child_collection_policy"
        ]
        == "mode-aware"
    )


@pytest.mark.parametrize("existing_dataset", [True, False])
def test_topology_guard_retains_dataset_and_checkpoint_and_updates_outcome(
    tmp_path, existing_dataset, caplog
):
    caplog.set_level("INFO")
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "topology",
            "--skip-devices",
            "--no-update-devices",
            "--skip-mesh-diagnostics",
            "--no-enrich-mac-counters",
        ]
    )
    args.td_data_dir = tmp_path
    device = {
        "id": "1111111111111111",
        "role": "router",
        "mlEidIid": "0000000000000000",
    }
    diagnostic_path = tmp_path / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME
    outcome_path = tmp_path / OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
    checkpoint_path = tmp_path / create_checkpoint_filename(diagnostic_path.name)
    old_dataset = b'[{"id":"previous-diagnostic"}]'
    old_scope = b'{"previous":"network-scope"}'
    old_checkpoint = b'[{"id":"previous-checkpoint"}]'
    old_outcome = b'{"deviceResults":[{"status":"completed"}]}'
    if existing_dataset:
        diagnostic_path.write_bytes(old_dataset)
        network_scope_path(diagnostic_path).write_bytes(old_scope)
        checkpoint_path.write_bytes(old_checkpoint)
        outcome_path.write_bytes(old_outcome)
    outcome = {
        "items": [],
        "deviceResults": [
            {
                "deviceId": device["id"],
                "status": "skipped",
                "skipReasonCode": "unresolved_mesh_local_iid",
                "mlEidIid": "0000000000000000",
                "attempts": 0,
            }
        ],
        "partial": True,
        "clearedDiagnostics": False,
        "attemptedCount": 0,
    }
    client = MagicMock()
    client.list_devices.return_value = [device]

    def fetch_all(selected, **kwargs):
        assert selected == [device]
        kwargs["on_checkpoint"]([], 1, 1, device["id"], "skipped")
        return outcome

    client.fetch_all_devices_diagnostics.side_effect = fetch_all

    with patch.object(
        topology_module,
        "emit_rest_payload_output",
        side_effect=AssertionError("guarded empty datasets must not be written"),
    ):
        topology_module.dispatch_topology(client, args, raw_arg=False)

    if existing_dataset:
        assert diagnostic_path.read_bytes() == old_dataset
        assert network_scope_path(diagnostic_path).read_bytes() == old_scope
        assert checkpoint_path.read_bytes() == old_checkpoint
    else:
        assert not diagnostic_path.exists()
        assert not network_scope_path(diagnostic_path).exists()
        assert not checkpoint_path.exists()
    saved_outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert saved_outcome["deviceResults"][0]["skipReasonCode"] == (
        "unresolved_mesh_local_iid"
    )
    assert saved_outcome["attemptedCount"] == 0
    assert "no new diagnostic data" in caplog.text


@pytest.mark.parametrize(
    ("skipped_steps", "expected_saved_paths", "diagnostics_calls", "mesh_calls"),
    [
        (
            [],
            [
                OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
                OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
                OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
                OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
            ],
            1,
            1,
        ),
        (
            ["--skip-diagnostics"],
            [
                OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME,
                OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
            ],
            0,
            1,
        ),
        (
            ["--skip-mesh-diagnostics"],
            [
                OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME,
                OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
            ],
            1,
            0,
        ),
        (["--skip-diagnostics", "--skip-mesh-diagnostics"], [], 0, 0),
    ],
)
def test_topology_skip_devices_no_update_writes_only_enabled_stage_outputs(
    tmp_path, skipped_steps, expected_saved_paths, diagnostics_calls, mesh_calls
):
    args = cli_module.build_parser().parse_args(
        [
            "--no-progress",
            "topology",
            "--skip-devices",
            "--no-update-devices",
            "--no-enrich-mac-counters",
            *skipped_steps,
        ]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    client.list_devices.return_value = [{"id": "listed", "rloc16": "0x4000"}]
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

    def save(_payload, path, _logger, *, on_write):
        saved_paths.append(path.name)
        on_write(True)

    with patch.object(topology_module, "emit_rest_payload_output", side_effect=save):
        assert topology_module.dispatch_topology(client, args, raw_arg=False) is None

    client.list_devices.assert_called_once_with(raw=False)
    client.fetch_device_collection.assert_not_called()
    assert client.fetch_all_devices_diagnostics.call_count == diagnostics_calls
    assert client.fetch_mesh_diagnostics_all_devices.call_count == mesh_calls
    assert OTBR_RESTAPI_DEVICES_FETCH_FILENAME not in saved_paths
    assert saved_paths == expected_saved_paths


@pytest.mark.parametrize(
    ("command", "command_attribute"),
    [
        (["diagnostics", "fetch-all"], "diagnostics_command"),
        (["mesh-diagnostics", "fetch-all"], "mesh_diag_command"),
    ],
)
def test_rest_fetch_all_parsers_accept_no_update_devices(command, command_attribute):
    args = cli_module.build_parser().parse_args([*command, "--no-update-devices"])

    assert getattr(args, command_attribute) == "fetch-all"
    assert args.no_update_devices is True


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


def _observed_topology(tmp_path, *flags):
    args = cli_module.build_parser().parse_args(
        ["topology", "--no-enrich-mac-counters", *flags]
    )
    args.td_data_dir = tmp_path
    client = MagicMock()
    devices = [
        {"id": "1111111111111111", "rloc16": "0x4000"},
        {"id": "bad", "rloc16": "0x8000"},
    ]
    client.fetch_device_collection.return_value = devices
    client.list_devices.return_value = devices
    outcome = {
        "items": [{"id": "diagnostic-one"}],
        "deviceResults": [
            {"deviceId": "1111111111111111", "status": "completed"},
            {"deviceId": "bad", "status": "skipped"},
        ],
        "inputCount": 2, "queriedCount": 1, "attemptedCount": 1, "partial": False,
    }
    client.fetch_all_devices_diagnostics.return_value = outcome
    client.fetch_mesh_diagnostics_all_devices.return_value = outcome
    return args, client, outcome


@pytest.mark.parametrize("progress_enabled", [False, True])
def test_topology_progress_has_owned_stages_and_separate_expansion(
    tmp_path, caplog, capsys, progress_enabled,
):
    args, client, outcome = _observed_topology(
        tmp_path, *([] if progress_enabled else ["--no-progress"])
    )

    def diagnostics(_selected, **kwargs):
        if kwargs["on_progress"] is not None:
            kwargs["on_rejected_progress"]("bad", 0.125, "malformed")
            kwargs["on_progress"](1, 1, "1111111111111111", 0.25, "completed")
            kwargs["on_progress"](1, 3, "rloc:0001", 0.375, "completed")
        return outcome

    def mesh(_selected, **kwargs):
        if kwargs["on_progress"] is not None:
            kwargs["on_rejected_progress"]("bad", 0.125, "malformed")
            kwargs["on_progress"](1, 1, "1111111111111111", 0.25, "completed")
        return outcome

    client.fetch_all_devices_diagnostics.side_effect = diagnostics
    client.fetch_mesh_diagnostics_all_devices.side_effect = mesh
    with caplog.at_level(logging.INFO):
        topology_module.dispatch_topology(client, args, False)
    captured = capsys.readouterr()
    assert not captured.out
    lines = captured.err.splitlines()
    assert len(lines) == (5 if progress_enabled else 0)
    if progress_enabled:
        assert all('command="topology"' in line for line in lines)
        assert 'stage="diagnostics.initial"' in lines[0] and 'progress="[1/2]"' in lines[0]
        assert 'stage="diagnostics.initial"' in lines[1] and 'progress="[2/2]"' in lines[1]
        assert 'stage="diagnostics.expansion"' in lines[2] and 'progress="[1/3]"' in lines[2]
        assert 'stage="mesh.initial"' in lines[3] and 'progress="[1/2]"' in lines[3]
        assert 'stage="mesh.initial"' in lines[4] and 'progress="[2/2]"' in lines[4]
    assert 'command="diagnostics fetch-all"' not in caplog.text
    assert 'stage="mesh.qualification" availability="unavailable"' in caplog.text
    starts = [r.message for r in caplog.records if 'event="step_start"' in r.message]
    ends = [r.message for r in caplog.records if 'event="step_end"' in r.message]
    assert len(starts) == len(ends) == 3
    assert ['stage="devices.fetch"' in starts[0], 'stage="diagnostics"' in starts[1],
            'stage="mesh"' in starts[2]] == [True, True, True]
    summary = next(r.message for r in caplog.records if 'event="workflow_summary"' in r.message)
    assert 'executed=3' in summary and 'skipped=0' in summary and 'failed=0' in summary


_TOPOLOGY_ARTIFACTS = [
    (OTBR_RESTAPI_DEVICES_FETCH_FILENAME, "devices.final"),
    (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_FILENAME, "diagnostics.final"),
    (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME, "diagnostics.outcome"),
    (OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME, "mesh.final"),
    (OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME, "mesh.outcome"),
]


@pytest.mark.parametrize("filename,stage", _TOPOLOGY_ARTIFACTS)
@pytest.mark.parametrize("disposition", ["retained_previous", "failed"])
def test_topology_observes_each_actual_publication(
    tmp_path, monkeypatch, caplog, filename, stage, disposition,
):
    import util_data

    args, client, _outcome = _observed_topology(tmp_path, "--no-progress")
    target = tmp_path / filename
    target.write_bytes(b"old snapshot\n")
    original = util_data.save_final_json

    def save(payload, path, *args, **kwargs):
        if Path(path).name == filename:
            if disposition == "failed":
                raise OSError("publication failed")
            return False
        return original(payload, path, *args, **kwargs)

    monkeypatch.setattr(util_data, "save_final_json", save)
    with caplog.at_level(logging.INFO):
        if disposition == "failed":
            with pytest.raises(OSError, match="publication failed"):
                topology_module.dispatch_topology(client, args, False)
        else:
            topology_module.dispatch_topology(client, args, False)
    writes = [
        r.message for r in caplog.records
        if r.message.startswith('event="write"') and f'stage="{stage}"' in r.message
    ]
    assert len(writes) == 1 and f'disposition="{disposition}"' in writes[0]
    assert target.read_bytes() == b"old snapshot\n"
    if disposition == "failed":
        summary = next(r.message for r in caplog.records if 'event="workflow_summary"' in r.message)
        assert 'state="raised"' in summary and 'failed=1' in summary
        if stage == "devices.final":
            client.fetch_all_devices_diagnostics.assert_not_called()
        if not stage.startswith("mesh."):
            client.fetch_mesh_diagnostics_all_devices.assert_not_called()


def test_topology_primary_then_scope_failure_is_not_saved(tmp_path, monkeypatch, caplog):
    import util_data

    args, client, _outcome = _observed_topology(tmp_path, "--no-progress")
    original = util_data.write_network_scope

    def scope(path, value):
        if Path(path).name == OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME:
            raise OSError("scope failed")
        return original(path, value)

    monkeypatch.setattr(util_data, "write_network_scope", scope)
    with caplog.at_level(logging.INFO), pytest.raises(OSError, match="scope failed"):
        topology_module.dispatch_topology(client, args, False)
    assert (tmp_path / OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_FILENAME).is_file()
    writes = [
        r.message for r in caplog.records
        if r.message.startswith('event="write"') and 'stage="mesh.final"' in r.message
    ]
    assert len(writes) == 1 and 'disposition="failed"' in writes[0]
    assert not (tmp_path / OTBR_RESTAPI_MESH_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME).exists()


@pytest.mark.parametrize("skip_devices", [False, True])
@pytest.mark.parametrize("skip_diagnostics", [False, True])
@pytest.mark.parametrize("skip_mesh", [False, True])
def test_topology_skipped_stages_keep_actual_operations_visible(
    tmp_path, caplog, skip_devices, skip_diagnostics, skip_mesh,
):
    flags = ["--no-progress", "--no-update-devices"]
    flags += ["--skip-devices"] if skip_devices else []
    flags += ["--skip-diagnostics"] if skip_diagnostics else []
    flags += ["--skip-mesh-diagnostics"] if skip_mesh else []
    args, client, _outcome = _observed_topology(tmp_path, *flags)
    with caplog.at_level(logging.INFO):
        topology_module.dispatch_topology(client, args, False)
    assert client.list_devices.call_count == int(skip_devices)
    assert client.fetch_device_collection.call_count == int(not skip_devices)
    assert client.fetch_all_devices_diagnostics.call_count == int(not skip_diagnostics)
    assert client.fetch_mesh_diagnostics_all_devices.call_count == int(not skip_mesh)
    skipped = sum([skip_devices, skip_diagnostics, skip_mesh])
    summary = next(r.message for r in caplog.records if 'event="workflow_summary"' in r.message)
    assert f'executed={3 - skipped}' in summary and f'skipped={skipped}' in summary
    if skip_devices:
        assert 'stage="devices.list" state="returned"' in caplog.text


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