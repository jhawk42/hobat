from __future__ import annotations

import json
from pathlib import Path

import pytest
import merge_dataset

from merge_dataset import (
    MergeCommandResult,
    build_merge_output,
    load_merge_supporting_data,
    parse_args,
    resolve_input_files,
    resolve_input_groups,
    resolve_merge_command_inputs,
    write_merge_outputs,
)


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_input_files_stably_deduplicates_before_exclusions() -> None:
    assert resolve_input_files(
        ["alpha.json", "beta.json", "alpha.json"],
        ["beta.json", "gamma.json", "gamma.json"],
        ["beta.json"],
    ) == ["alpha.json", "gamma.json"]


def test_resolve_input_groups_preserves_group_and_file_order() -> None:
    resolved = resolve_input_groups(["otbr-cli", "otbr-restapi"])
    assert resolved == list(dict.fromkeys(resolved))
    assert resolved[0] == "td-otbr-cli-router-table.json"
    assert resolved[-1] == "td-otbr-restapi-devices.json"


def test_resolve_input_groups_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match=r"Unknown input group\(s\): missing"):
        resolve_input_groups(["missing"])


def test_resolve_merge_command_inputs_classifies_paths_without_loading(tmp_path: Path) -> None:
    _write_json(tmp_path / "required.json", [{"rloc16": "0x1234"}])
    args = parse_args([
        "--base-dir", str(tmp_path),
        "--include-groups", "",
        "--include-files", "required.json",
        "--output", "nested/merged.json",
        "--report-file", "nested/report.json",
    ])

    inputs = resolve_merge_command_inputs(args, tmp_path)

    assert inputs.data_dir == tmp_path
    assert inputs.input_files == ("required.json",)
    assert inputs.loaded_input_files == ("required.json",)
    assert inputs.required_files == frozenset({"required.json"})
    assert inputs.skipped_files == ()
    assert inputs.output_path == tmp_path / "nested/merged.json"
    assert inputs.report_path == tmp_path / "nested/report.json"


def test_support_loading_reports_missing_reference_fallbacks(tmp_path: Path) -> None:
    _write_json(tmp_path / "required.json", [{"rloc16": "0x1234"}])
    args = parse_args([
        "--base-dir", str(tmp_path),
        "--include-groups", "",
        "--include-files", "required.json",
    ])
    inputs = resolve_merge_command_inputs(args, tmp_path)

    support = load_merge_supporting_data(inputs)

    assert support.device_label_map == {}
    assert support.network_info == {}
    assert support.omr_prefix == ""
    assert all(item["fallback"] for item in support.reference_files)


def test_build_and_write_merge_output_are_independently_testable(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "required.json",
        [{"rloc16": "0x1234", "extaddr": "aabbccddeeff0011"}],
    )
    args = parse_args([
        "--base-dir", str(tmp_path),
        "--include-groups", "",
        "--include-files", "required.json",
        "--output", "merged.json",
        "--report-file", "report.json",
        "--merge-strategy", "none",
        "--matter-identity-mode", "composite-guard",
    ])
    inputs = resolve_merge_command_inputs(args, tmp_path)
    support = load_merge_supporting_data(inputs)

    result = build_merge_output(inputs, support)

    assert result.viable is True
    assert result.viability_reason is None
    assert result.report["merge_strategy"] == "none"
    assert result.report["passthrough_record_count"] == 1
    assert not inputs.output_path.exists()
    write_merge_outputs(result, inputs.output_path, inputs.report_path)
    assert json.loads(inputs.output_path.read_text(encoding="utf-8")) == result.records
    assert json.loads(inputs.report_path.read_text(encoding="utf-8")) == result.report


def test_build_merge_output_loads_each_passthrough_source_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_json(tmp_path / "first.json", [{"rloc16": "0x1234"}])
    _write_json(tmp_path / "second.json", [{"rloc16": "0x5678"}])
    args = parse_args([
        "--base-dir", str(tmp_path),
        "--include-groups", "",
        "--include-files", "first.json", "second.json",
        "--merge-strategy", "none",
    ])
    inputs = resolve_merge_command_inputs(args, tmp_path)
    support = load_merge_supporting_data(inputs)
    original_load_json = merge_dataset.load_json
    loaded_paths: list[Path] = []

    def tracking_load_json(path: Path):
        loaded_paths.append(path)
        return original_load_json(path)

    monkeypatch.setattr(merge_dataset, "load_json", tracking_load_json)
    build_merge_output(inputs, support)

    assert loaded_paths == [tmp_path / "first.json", tmp_path / "second.json"]


def test_merge_output_records_are_stable_under_reordered_includes(tmp_path: Path) -> None:
    _write_json(tmp_path / "first.json", [{"rloc16": "0x1234", "name": "a"}])
    _write_json(tmp_path / "second.json", [{"rloc16": "0x5678", "name": "b"}])

    def build(include_files: list[str]):
        args = parse_args([
            "--base-dir", str(tmp_path),
            "--include-groups", "",
            "--include-files", *include_files,
        ])
        inputs = resolve_merge_command_inputs(args, tmp_path)
        return build_merge_output(inputs, load_merge_supporting_data(inputs))

    assert build(["first.json", "second.json"]).records == build(
        ["second.json", "first.json"]
    ).records


def test_malformed_support_payload_uses_documented_fallback(tmp_path: Path) -> None:
    _write_json(tmp_path / "required.json", [{"rloc16": "0x1234"}])
    (tmp_path / "network.json").write_text("{", encoding="utf-8")
    args = parse_args([
        "--base-dir", str(tmp_path),
        "--include-groups", "",
        "--include-files", "required.json",
        "--dataset-file", "network.json",
    ])
    inputs = resolve_merge_command_inputs(args, tmp_path)

    support = load_merge_supporting_data(inputs)

    assert support.network_info == {}
    assert support.reference_files[1] == {
        "file": "network.json",
        "loaded": False,
        "fallback": True,
    }


def test_write_merge_outputs_does_not_replace_target_on_serialization_failure(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "merged.json"
    output_path.write_text('{"existing": true}\n', encoding="utf-8")
    result = MergeCommandResult(
        records=[{"invalid": object()}],
        report={},
        viable=True,
        viability_reason=None,
    )

    with pytest.raises(TypeError):
        write_merge_outputs(result, output_path)

    assert output_path.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert not (tmp_path / "merged.json.tmp").exists()


def test_write_merge_outputs_does_not_replace_targets_when_not_viable(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "merged.json"
    report_path = tmp_path / "report.json"
    output_path.write_text('[{"existing": true}]\n', encoding="utf-8")
    report_path.write_text('{"existing": true}\n', encoding="utf-8")
    result = MergeCommandResult(
        records=[],
        report={"viable": False},
        viable=False,
        viability_reason="no viable seed identities found",
    )

    with pytest.raises(ValueError, match="no viable seed identities found"):
        write_merge_outputs(result, output_path, report_path)

    assert output_path.read_text(encoding="utf-8") == '[{"existing": true}]\n'
    assert report_path.read_text(encoding="utf-8") == '{"existing": true}\n'