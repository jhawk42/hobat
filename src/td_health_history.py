"""Public health history and explicit expected-roster operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from td_device_fields import get_canonical_ext_address
from td_health_manifest import load_health_manifest
from td_health_observation_model import device_id_from_ext_address, network_id_from_ext_pan_id
from td_health_processor import HealthProcessingError
from td_health_sqlite import SQLiteHealthStore


@dataclass(frozen=True)
class RosterImportResult:
    network_id: str
    imported: int
    skipped: int


def network_id_for_dataset(*, data_dir: Path, dataset_id: str) -> str:
    dataset = load_health_manifest().dataset(dataset_id)
    identity_path = data_dir / dataset.health_profile.identity_file
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthProcessingError(f"Cannot read roster identity: {exc}") from exc
    if not isinstance(identity, dict):
        raise HealthProcessingError("Identity context must be a JSON object")
    try:
        return network_id_from_ext_pan_id(identity.get("extPanId"))
    except ValueError as exc:
        raise HealthProcessingError(f"Invalid extPanId identity: {exc}") from exc


def import_expected_roster_from_label_map(
    *, data_dir: Path, dataset_id: str, store: SQLiteHealthStore
) -> RosterImportResult:
    network_id = network_id_for_dataset(data_dir=data_dir, dataset_id=dataset_id)
    label_map_path = data_dir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    try:
        label_map = json.loads(label_map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthProcessingError(f"Cannot import expected roster: {exc}") from exc
    if not isinstance(label_map, list):
        raise HealthProcessingError("Label map must be a JSON array")

    imported = 0
    skipped = 0
    for record in label_map:
        if not isinstance(record, dict):
            skipped += 1
            continue
        try:
            device_id = device_id_from_ext_address(get_canonical_ext_address(record))
        except ValueError:
            skipped += 1
            continue
        label = record.get("deviceLabel", record.get("device_label"))
        store.upsert_expected_device(
            network_id, device_id, label if isinstance(label, str) else None
        )
        imported += 1
    return RosterImportResult(network_id, imported, skipped)