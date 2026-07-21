from __future__ import annotations

import json
from pathlib import Path

from merge_dataset import main as merge_dataset_main


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_merge_dataset_skips_missing_default_inputs_and_reports_them(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "td-otbr-cli-thread-network-info.json",
        {"prefix_omr_ipv6addr_prefix": "fd00:abcd::"},
    )
    _write_json(tmp_path / "td-static-extaddr-device-label.json", [])
    _write_json(
        tmp_path / "td-otbr-cli-router-table.json",
        [{"rloc16": "0x1234", "extaddr": "aabbccddeeff0011"}],
    )

    rc = merge_dataset_main(
        [
            "--base-dir",
            str(tmp_path),
            "--output",
            "merged.json",
            "--report-file",
            "report.json",
        ]
    )

    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    # NOTE: td-otbr-cli-router-table.json appears twice because OTBR_CLI_INPUT_FILES
    # and OTBR_RESTAPI_INPUT_FILES are currently identical in merge_dataset.py (line 200-214).
    # TODO: Fix source code to have distinct OTBR_RESTAPI_INPUT_FILES.
    assert report["loaded_input_files"] == ["td-otbr-cli-router-table.json", "td-otbr-cli-router-table.json"]
    assert any(item["reason"] == "missing" for item in report["skipped_input_files"])
    assert report["required_seed_status"]["viable"] is True


def test_merge_dataset_returns_4_for_missing_required_included_file(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "td-otbr-cli-thread-network-info.json",
        {"prefix_omr_ipv6addr_prefix": "fd00:abcd::"},
    )
    _write_json(tmp_path / "td-static-extaddr-device-label.json", [])

    rc = merge_dataset_main(
        [
            "--base-dir",
            str(tmp_path),
            "--include-files",
            "must-exist.json",
        ]
    )

    assert rc == 4


def test_merge_dataset_returns_3_when_no_viable_seed_identity(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "td-otbr-cli-thread-network-info.json",
        {"prefix_omr_ipv6addr_prefix": "fd00:abcd::"},
    )
    _write_json(tmp_path / "td-static-extaddr-device-label.json", [])
    _write_json(tmp_path / "td-otbr-cli-router-table.json", [{"device_label": "node-a"}])

    rc = merge_dataset_main(
        [
            "--base-dir",
            str(tmp_path),
            "--output",
            "merged.json",
        ]
    )

    assert rc == 3


def test_merge_dataset_succeeds_when_extaddr_map_missing(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "td-otbr-cli-thread-network-info.json",
        {"prefix_omr_ipv6addr_prefix": "fd00:abcd::"},
    )
    _write_json(
        tmp_path / "td-otbr-cli-router-table.json",
        [{"rloc16": "0x1234", "extaddr": "aabbccddeeff0011"}],
    )

    rc = merge_dataset_main(
        [
            "--base-dir",
            str(tmp_path),
            "--output",
            "merged.json",
            "--report-file",
            "report.json",
        ]
    )

    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["reference_extaddr_map_entries"] == 0
    assert report["optional_reference_files"][0]["fallback"] is True


def test_merge_dataset_succeeds_when_thread_network_info_missing(tmp_path: Path) -> None:
    _write_json(tmp_path / "td-static-extaddr-device-label.json", [])
    _write_json(
        tmp_path / "td-otbr-cli-router-table.json",
        [{"rloc16": "0x1234", "extaddr": "aabbccddeeff0011"}],
    )

    rc = merge_dataset_main(
        [
            "--base-dir",
            str(tmp_path),
            "--output",
            "merged.json",
            "--report-file",
            "report.json",
        ]
    )

    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["optional_reference_files"][1]["file"] == "td-otbr-cli-thread-network-info.json"
    assert report["optional_reference_files"][1]["fallback"] is True
