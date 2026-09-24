from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from td_device_fields import (
    get_canonical_ext_address as get_canonical_extaddr,
    get_canonical_omr_address as get_canonical_omr,
    is_placeholder_ext_address as is_placeholder_extaddr,
    is_placeholder_omr_address,
    normalize_identifier_text,
)
from td_network_identity import NetworkScope
from util_data import save_json_atomic, write_network_scope


@dataclass(frozen=True)
class MergeCommandInputs:
    data_dir: Path
    input_files: tuple[str, ...]
    required_files: frozenset[str]
    loaded_input_files: tuple[str, ...]
    skipped_files: tuple[dict[str, str], ...]
    dataset_path: Path
    extaddr_map_path: Path
    output_path: Path
    report_path: Path | None
    dataset_file: str
    extaddr_map_file: str
    merge_strategy: str
    matter_identity_mode: str


@dataclass(frozen=True)
class MergeSupportingData:
    device_label_map: dict[str, Any]
    network_info: dict[str, Any]
    omr_prefix: str
    reference_files: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class MergeCommandResult:
    records: list[dict[str, Any]]
    report: dict[str, Any]
    viable: bool
    viability_reason: str | None


def evaluate_merge_viability(
    records: Sequence[dict[str, Any]],
) -> tuple[bool, int, str | None]:
    identity_seed_record_count = 0
    for node in records:
        extaddr = get_canonical_extaddr(node)
        rloc16 = normalize_identifier_text(node.get("rloc16"))
        omr_addr = get_canonical_omr(node)
        if (
            (extaddr and not is_placeholder_extaddr(extaddr))
            or rloc16
            or (omr_addr and not is_placeholder_omr_address(omr_addr))
        ):
            identity_seed_record_count += 1

    viable = identity_seed_record_count > 0
    reason = None if viable else "no viable seed identities found in loaded input files"
    return viable, identity_seed_record_count, reason


def write_merge_outputs(
    result: MergeCommandResult,
    output_path: Path,
    report_path: Path | None = None,
) -> None:
    if not result.viable:
        raise ValueError(result.viability_reason or "merge output is not viable")
    save_json_atomic(
        result.records,
        output_path,
        indent=2,
        add_trailing_newline=True,
    )
    instance = result.report.get("networkInstance")
    if instance:
        write_network_scope(output_path, NetworkScope(
            instance["extPanId"], instance["networkName"], instance["provenance"],
            "no-ext-pan-id-observed" if instance["extPanId"] is None else None,
            datetime.now(timezone.utc).isoformat(), tuple(instance["sources"]),
        ))
    if report_path is not None:
        save_json_atomic(
            result.report,
            report_path,
            indent=2,
            add_trailing_newline=True,
        )
