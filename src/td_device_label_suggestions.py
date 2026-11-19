"""Read-only, source-backed HA Matter device name suggestions."""

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from device_label import (
    _load_static_records_strict,
    _map_lock,
    _record_extaddr,
    _save_map,
    _timestamp,
    normalize_valid_device_label,
    normalize_valid_extaddr,
)
from td_dataset_catalog import load_dataset_catalog, resolve_dataset, unique_json_object
from td_health_manifest import MANIFEST_PATH
from td_network_identity import network_id_from_ext_pan_id
from util_data import data_file_path, network_scope_path

SOURCE = "ha-matter-ws"
DATASET = "ha_matter_ws_devices"


def apply_name_suggestions(
    map_path: Path, preview: Callable[[], dict], from_preview: Path, select: Sequence[str],
) -> dict:
    """Revalidate a reviewed source preview under the shared map write lock."""
    from td_device_label_sync import _serialize_preserving_rows

    if not select or len(select) != len(set(select)):
        raise ValueError("specify one or more distinct --select IDs")
    reviewed = json.loads(from_preview.read_bytes(), object_pairs_hook=unique_json_object)
    with _map_lock(map_path):
        current = preview()
        if reviewed != current:
            raise ValueError("reviewed preview no longer matches current inputs or decisions")
        eligible = {row["id"]: row for row in current["candidates"] if row["state"] == "resolved"}
        if not set(select) <= eligible.keys():
            raise ValueError("selection includes an unknown or ineligible candidate")

        proposed = {}
        for item in select:
            candidate = eligible[item]
            address = candidate["extAddress"]
            label = candidate["deviceLabel"]
            if address in proposed and proposed[address] != label:
                raise ValueError("selection contains competing labels for one address")
            proposed[address] = label

        fingerprints = {}
        before = _load_static_records_strict(map_path, allow_missing=True, fingerprints=fingerprints)
        map_digest = current["inputFingerprints"]["map"]
        if fingerprints["map"] != map_digest:
            raise ValueError("label map changed during apply; generate a new preview")
        occupied = {_record_extaddr(row) for row in before}
        occupied.update(normalize_valid_extaddr(addr) for row in before
                        for addr in row.get("previousExtAddresses", []))
        if occupied.intersection(proposed):
            raise ValueError("selection includes an address already in the label map or its history")
        stamp = _timestamp(None)
        inserted = [{"extAddress": addr, "deviceLabel": label, "lastUpdated": stamp}
                    for addr, label in sorted(proposed.items())]
        after = sorted([*before, *inserted], key=_record_extaddr)
        serialized = None
        if map_digest is not None:
            raw = map_path.read_bytes()
            if _digest(raw) != map_digest:
                raise ValueError("label map changed during apply; generate a new preview")
            serialized = _serialize_preserving_rows(raw, before, after)
        if preview() != current:
            raise ValueError("inputs changed during apply; generate a new preview")
        _save_map(after, map_path, serialized=serialized)
        return {**current, "applied": sorted(select), "inserted": inserted}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _row_candidate(row: object, network: str) -> tuple[str | None, str | None, str | None]:
    if not isinstance(row, dict):
        return None, None, "malformed-row"
    thread = row.get("thread")
    try:
        address = normalize_valid_extaddr(thread.get("extAddress") if isinstance(thread, dict) else None)
        if address in ("0000000000000000", "ffffffffffffffff"):
            raise ValueError("placeholder address")
    except ValueError:
        return None, None, "missing-or-invalid-thread-address"
    matter = row.get("matter")
    try:
        label = normalize_valid_device_label(matter.get("rawNodeLabel") if isinstance(matter, dict) else None)
    except ValueError:
        return address, None, "missing-or-invalid-raw-node-label"
    try:
        row_network = network_id_from_ext_pan_id(thread.get("extendedPanId"))
    except ValueError:
        row_network = None
    if row_network != network:
        return address, label, "unverified-row-network"
    return address, label, None


def preview_ha_matter_names(data_dir: Path, map_path: Path, network: str) -> dict:
    """Suggest names only from the same raw inventory row as the Thread identity."""
    if not re.fullmatch(r"extpan:[0-9a-fA-F]{16}", network):
        raise ValueError("network must be extpan:<16 hexadecimal digits>")
    network = network_id_from_ext_pan_id(network.split(":", 1)[1])
    manifest = MANIFEST_PATH.read_bytes()
    dataset = resolve_dataset(load_dataset_catalog(), DATASET, SOURCE)
    if MANIFEST_PATH.read_bytes() != manifest:
        raise ValueError("dataset catalog changed during preview")
    filename, = dataset["files"]
    snapshot = data_file_path(filename, data_dir)
    companion = network_scope_path(snapshot)
    raw, scope_bytes = snapshot.read_bytes(), companion.read_bytes()
    scope = json.loads(scope_bytes, object_pairs_hook=unique_json_object)
    if (not isinstance(scope, dict) or scope.get("provenance") != "observed"
            or scope.get("snapshotSha256") != _digest(raw)
            or scope.get("sources") != [filename]
            or scope.get("extPanId") != network.split(":", 1)[1]):
        raise ValueError("HA Matter inventory needs a digest-bound observed scope from this inventory on the selected network")
    rows = json.loads(raw, object_pairs_hook=unique_json_object)
    if not isinstance(rows, list):
        raise ValueError("HA Matter inventory must contain a JSON list")

    fingerprints = {
        "@dataset-manifest": _digest(manifest),
        filename: _digest(raw),
        companion.name: _digest(scope_bytes),
    }
    records = _load_static_records_strict(map_path, allow_missing=True, fingerprints=fingerprints)
    mapped = {_record_extaddr(record) for record in records}
    history = {
        normalize_valid_extaddr(address)
        for record in records for address in record.get("previousExtAddresses", [])
    }
    grouped: dict[str, dict[str, list[int]]] = {}
    candidates = []
    for index, row in enumerate(rows):
        address, label, reason = _row_candidate(row, network)
        if address is not None and label is not None and reason is None:
            grouped.setdefault(address, {}).setdefault(label, []).append(index)
        else:
            candidates.append(_candidate(address, label, "ineligible", reason, [index]))

    for address, names in sorted(grouped.items()):
        for label, indexes in sorted(names.items()):
            if address in mapped or address in history:
                state, reason = "ineligible", "address-already-mapped"
            elif len(names) > 1:
                state, reason = "conflict", "distinct-node-labels-for-address"
            else:
                state, reason = "resolved", None
            candidates.append(_candidate(address, label, state, reason, indexes))

    return {
        "schemaVersion": 1,
        "source": SOURCE,
        "dataset": DATASET,
        "networkId": network,
        "snapshot": filename,
        "scopeCompanion": companion.name,
        "inputFingerprints": fingerprints,
        "candidates": candidates,
    }


def _candidate(
    address: str | None, label: str | None, state: str, reason: str | None, indexes: list[int],
) -> dict:
    key = [SOURCE, DATASET, address, label, indexes if state == "ineligible" else None]
    return {
        "id": _digest(json.dumps(key, separators=(",", ":")).encode()),
        "extAddress": address,
        "deviceLabel": label,
        "state": state,
        "reason": reason,
        "evidence": [
            {"address": f"/{index}/thread/extAddress", "network": f"/{index}/thread/extendedPanId",
             "label": f"/{index}/matter/rawNodeLabel", "matterAttribute": "0/40/5"}
            for index in indexes
        ],
    }
