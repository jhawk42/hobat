"""Reviewed, transactional import of sweep EUIs into the roster alias store."""

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from td_health_sqlite import (
    SCHEMA_VERSION,
    SQLiteHealthStore,
    _create_migration_backup,
    apply_registered_schema_migrations,
    validate_health_schema_connection,
)
from td_health_sweep_evidence import digest_bytes, read_sweep
from td_network_identity import network_id_from_ext_pan_id


def _fingerprint(value: object) -> str:
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _preview(connection: sqlite3.Connection, version: int, network: str, receipt: str,
             completion: str, frames: list[dict]) -> dict:
    addresses = {}
    normal = {}
    aliases = {}
    for row in connection.execute(
        """SELECT k.field_key, k.value_json, d.ext_address
           FROM device_last_known AS k JOIN devices AS d USING (device_id)
           WHERE k.network_id=? AND k.field_key IN ('extAddress', 'eui')""", (network,),
    ):
        (addresses if row["field_key"] == "extAddress" else normal)[row["ext_address"]] = (
            json.loads(row["value_json"])
        )
    if version >= 11:
        aliases = {row["ext_address"]: row["eui"] for row in connection.execute(
            """SELECT d.ext_address, a.eui FROM roster_eui_aliases AS a
               JOIN devices AS d USING (device_id) WHERE a.network_id=?""", (network,),
        )}
    observations = defaultdict(list)
    observed_owners = defaultdict(set)
    stored_owners = defaultdict(set)
    for frame in frames:
        ext, eui = frame["extAddress"], frame["eui"]
        observations[ext].append(frame)
        if eui and int(eui, 16):
            observed_owners[eui].add(ext)
    for facts in (normal, aliases):
        for ext, eui in facts.items():
            stored_owners[eui].add(ext)

    candidates = []
    roster_state = {}
    for ext, evidence in sorted(observations.items()):
        euis = sorted({item["eui"] for item in evidence if item["eui"] and int(item["eui"], 16)})
        eui = euis[0] if len(euis) == 1 else None
        owners = sorted(stored_owners[eui] - {ext})
        current = {value for value in (normal.get(ext), aliases.get(ext)) if value is not None}
        roster_state[ext] = [addresses.get(ext), normal.get(ext), aliases.get(ext), owners]
        if len(euis) > 1:
            state, reason = "conflict", "disagreeing-replies"
        elif eui is None:
            state, reason = "ineligible", "no-valid-eui" if "stream" in evidence[0] else "no-reply"
        elif addresses.get(ext) != ext:
            state, reason = "ineligible", "unknown-roster-device"
        elif owners or len(observed_owners[eui]) != 1:
            state, reason = "conflict", "shared-eui"
        elif current - {eui}:
            state, reason = "conflict", "different-stored-eui"
        elif current:
            state, reason = "already-matching", None
        else:
            state, reason = "fill-eui", None
        candidates.append({
            "id": _fingerprint([network, ext, euis, receipt, completion]), "extAddress": ext,
            "eui": eui, "state": state, "reason": reason, "evidence": evidence,
        })
    return {"version": 1, "networkId": network, "evidenceSha256": receipt,
            "completionSha256": completion,
            "rosterSha256": _fingerprint(roster_state), "candidates": candidates,
            "counts": dict(sorted(Counter(row["state"] for row in candidates).items()))}


def backfill_roster_eui(database: Path, *, network: str, evidence_dir: Path,
                        reviewed: dict | None = None, selected: tuple[str, ...] = (),
                        all_eligible: bool = False) -> dict:
    if not network.startswith("extpan:") or network_id_from_ext_pan_id(network[7:]) != network:
        raise ValueError("--network requires a canonical Extended PAN ID")
    if reviewed is None and (selected or all_eligible):
        raise ValueError("Selection requires a saved preview")
    if reviewed is not None and (bool(selected) == all_eligible or len(selected) != len(set(selected))):
        raise ValueError("Choose distinct --select IDs or --all-eligible")
    if not database.is_file():
        raise ValueError("Health store is not available")
    store = SQLiteHealthStore(database, read_only=True)
    connect = store._connect if reviewed is None else store._connect_existing_write
    with closing(connect()) as connection, connection:
        connection.execute("BEGIN" if reviewed is None else "BEGIN IMMEDIATE")
        version = validate_health_schema_connection(connection)
        if version < 10:
            raise ValueError("Update the health store to schema v10 or later before backfill")
        receipt, completion, frames = read_sweep(evidence_dir, network)
        preview = _preview(connection, version, network, receipt, completion, frames)
        if reviewed is None:
            return preview
        if reviewed != preview:
            raise ValueError("Saved preview no longer matches the evidence or roster; review a fresh preview")
        available = {row["id"]: row for row in preview["candidates"] if row["state"] == "fill-eui"}
        chosen = sorted(available if all_eligible else selected)
        if set(chosen) - available.keys():
            raise ValueError("Selection includes unknown, conflicting, or ineligible candidates")
        if not chosen:
            return {**preview, "applied": [], "backupPath": None}
        backup = _create_migration_backup(database, version, SCHEMA_VERSION)
        if read_sweep(evidence_dir, network) != (receipt, completion, frames):
            raise ValueError("Sweep evidence changed while preparing apply")
        if version < SCHEMA_VERSION:
            apply_registered_schema_migrations(connection, expected_source_version=version)
        for candidate_id in chosen:
            row = available[candidate_id]
            connection.execute(
                """INSERT INTO roster_eui_aliases (network_id, device_id, eui, provenance_json)
                   VALUES (?, ?, ?, ?)""",
                (network, "extaddr:" + row["extAddress"], row["eui"], json.dumps(
                    {"receiptSha256": receipt, "replies": [
                        entry for entry in row["evidence"] if entry["eui"] == row["eui"]
                    ]}, sort_keys=True,
                )),
            )
        return {**preview, "applied": chosen, "backupPath": str(backup)}
