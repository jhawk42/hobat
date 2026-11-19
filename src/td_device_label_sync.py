"""Reviewed, cache-only EUI maintenance for the device-label map.

Qualified cache evidence can fill EUIs. Explicit retained capture pairs
can support individually reviewed label-map moves, not roster retirement.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from device_label import (
    _load_static_records_strict,
    _map_lock,
    _record_eui,
    _record_extaddr,
    _save_map,
    _timestamp,
    _validate_records,
    normalize_valid_eui,
    normalize_valid_extaddr,
)
from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    OTBR_CLI_THREAD_NETWORK_INFO_FILENAME,
    OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
)
from td_dataset_catalog import load_dataset_catalog, resolve_dataset
from td_health_manifest import MANIFEST_PATH
from td_network_identity import network_id_from_ext_pan_id
from util_data import network_scope_path


class SyncEvidenceError(ValueError):
    """The reviewed preview or its evidence cannot safely be applied."""


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _time(value):
    if not isinstance(value, str):
        raise ValueError("missing capture time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("capture time has no timezone")
    return parsed.astimezone(timezone.utc)


def _cache_inputs(data_dir):
    manifest = _read(MANIFEST_PATH)
    catalog = load_dataset_catalog()
    if _read(MANIFEST_PATH) != manifest:
        raise SyncEvidenceError("dataset catalog changed during preview")
    cli_name = resolve_dataset(catalog, "otbr_cli_diagnostics_fetch", "otbr-cli")["files"][0]
    names = {
        cli_name,
        resolve_dataset(catalog, "otbr_restapi_diagnostics_fetch", "otbr-restapi")["files"][0],
        OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME,
    }
    files = {"@dataset-manifest": manifest}
    cli_mtime = None
    for name in sorted(names):
        path = data_dir / name
        if name == cli_name:
            try:
                before = path.stat().st_mtime_ns
                files[name] = path.read_bytes()
                cli_mtime = path.stat().st_mtime_ns
            except FileNotFoundError:
                files[name] = None
                cli_mtime = None
            else:
                if cli_mtime != before:
                    raise SyncEvidenceError("CLI diagnostics changed during preview")
        else:
            files[name] = _read(path)
        scope_path = network_scope_path(path)
        files[scope_path.name] = _read(scope_path)
    return files, cli_name, cli_mtime


def _scope(files, name):
    raw = files.get(name)
    sidecar = files.get(network_scope_path(name).name)
    if raw is None or sidecar is None:
        return None
    try:
        value = json.loads(sidecar)
        if (not isinstance(value, dict) or value.get("provenance") != "observed"
                or value.get("snapshotSha256") != _digest(raw)):
            return None
        return network_id_from_ext_pan_id(value["extPanId"])
    except (ValueError, KeyError, TypeError):
        return None


def _rest_observations(files, network_id, now, max_age):
    name = OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
    if _scope(files, name) != network_id:
        return {}
    try:
        outcome = json.loads(files[name])
        started = _time(outcome["startedAt"])
        completed = _time(outcome["completedAt"])
        if (outcome.get("clearedDiagnostics") is not True or started > completed
                or completed > now or (now - started).total_seconds() > max_age):
            return {}
        items = outcome["items"]
        results = outcome["deviceResults"]
        if not isinstance(items, list) or not isinstance(results, list):
            return {}
        recovery = outcome.get("diagnosticRecovery", {}).get("devices", [])
        if not isinstance(recovery, list):
            return {}
        recovered = {
            normalize_valid_extaddr(item["extAddress"])
            for item in recovery
            if isinstance(item, dict) and item.get("recoveryKind") != "none"
            and item.get("extAddress")
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        return {}

    direct = set()
    for result in results:
        if not isinstance(result, dict) or result.get("status") != "completed":
            continue
        types = result.get("successfulTypes")
        if (not isinstance(types, list) or not {"extAddress", "eui"}.issubset(types)
                or result.get("fallbackRecovered") is not False):
            continue
        try:
            address = normalize_valid_extaddr(result["deviceId"])
            diagnostic_id = result["diagnosticId"]
            created = _time(result["created"])
            if (isinstance(diagnostic_id, str) and address not in recovered
                    and started <= created <= completed):
                direct.add((address, diagnostic_id, created))
        except (ValueError, KeyError, TypeError):
            continue
    observations = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            address = normalize_valid_extaddr(item["extAddress"])
            eui = normalize_valid_eui(item["eui"])
            if (address, item.get("id"), _time(item["created"])) in direct:
                observations.setdefault(address, set()).add(eui)
        except (KeyError, ValueError, TypeError):
            continue
    return observations


def _cache_disagreements(files, network_id):
    observations = {}
    for name in sorted(files):
        if (name.endswith(".network.json")
                or name == OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME
                or _scope(files, name) != network_id):
            continue
        try:
            rows = json.loads(files[name])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    address = normalize_valid_extaddr(row["extAddress"])
                    eui = normalize_valid_eui(row.get("eui", row.get("eui64")))
                    observations.setdefault(address, set()).add(eui)
                except (KeyError, ValueError, TypeError):
                    continue
        except (ValueError, TypeError):
            continue
    return observations


def _cli_observations(files, name, mtime_ns, network_id, now, max_age):
    if mtime_ns is None or _scope(files, name) != network_id:
        return {}
    fallback = datetime.fromtimestamp(mtime_ns / 1e9, timezone.utc)
    try:
        records = json.loads(files[name])
    except (ValueError, TypeError):
        return {}
    observations = {}
    for row in records if isinstance(records, list) else ():
        if not isinstance(row, dict):
            continue
        try:
            address = normalize_valid_extaddr(row["extAddress"])
            eui = normalize_valid_eui(row.get("eui", row.get("eui64")))
            observed = _time(row["capturedAtIso"]) if "capturedAtIso" in row else fallback
            if 0 <= (now - observed).total_seconds() <= max_age:
                observations.setdefault(address, set()).add(eui)
        except (ValueError, KeyError, TypeError):
            continue
    return observations


def _object_spans(content):
    """Return exact top-level array member bytes, without surrounding whitespace."""
    text = content.decode("utf-8")
    decoder = json.JSONDecoder()
    pos = 0

    def whitespace(index):
        while index < len(text) and text[index] in " \r\n\t":
            index += 1
        return index

    pos = whitespace(pos)
    if pos == len(text) or text[pos] != "[":
        raise SyncEvidenceError("map is not a JSON array")
    pos = whitespace(pos + 1)
    spans = []
    while pos < len(text) and text[pos] != "]":
        start = pos
        _, pos = decoder.raw_decode(text, pos)
        spans.append(text[start:pos].encode("utf-8"))
        pos = whitespace(pos)
        if pos < len(text) and text[pos] == ",":
            pos = whitespace(pos + 1)
        else:
            break
    if pos >= len(text) or text[pos] != "]" or whitespace(pos + 1) != len(text):
        raise SyncEvidenceError("invalid map array")
    return spans


def _serialize_preserving_rows(original, before, after):
    """Keep the original JSON object text of every untouched row."""
    old_spans = _object_spans(original)
    new_spans = _object_spans(json.dumps(after, indent=4).encode("utf-8"))
    if len(old_spans) != len(before) or len(new_spans) != len(after):
        raise SyncEvidenceError("cannot locate original row bytes")
    old_rows = {_record_extaddr(row): (row, old_spans[index])
                for index, row in enumerate(before)}
    for index, row in enumerate(after):
        old_row, old_span = old_rows.get(_record_extaddr(row), (None, None))
        if row == old_row:
            new_spans[index] = old_span
    return "[\n    " + ",\n    ".join(span.decode("utf-8") for span in new_spans) + "\n]"


def _candidate_id(address, eui):
    return _digest(json.dumps([address, eui], separators=(",", ":")).encode())[:24]


def _retained_capture(directory, label, network_id, now, max_age):
    directory = Path(directory)
    snapshot = OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
    info = OTBR_CLI_THREAD_NETWORK_INFO_FILENAME
    files = {"run.meta": (directory / "run.meta").read_bytes()}
    meta = {}
    try:
        for line in files["run.meta"].decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if not key or not separator or key in meta:
                raise ValueError("invalid or duplicate run metadata field")
            meta[key] = value
        if meta["label"] != label or meta["capture_status"] != "verified-network":
            raise ValueError("capture label or status does not match")
        previous_end = None
        for stage, name in (("network_start", info), ("fetch_all", snapshot),
                            ("network_end", f"network-end/{info}")):
            started = _time(meta[f"{stage}_started_utc"])
            ended = _time(meta[f"{stage}_ended_utc"])
            if (meta[f"{stage}_exit"] != "0" or started >= ended or ended > now
                    or (previous_end is not None and previous_end > started)
                    or (now - started).total_seconds() > max_age):
                raise ValueError("failed, stale, future, or unordered collection stage")
            previous_end = ended
            companion = network_scope_path(name).as_posix()
            files[name] = (directory / name).read_bytes()
            files[companion] = (directory / companion).read_bytes()
            if _scope(files, name) != network_id:
                raise ValueError(f"{name} has no matching observed network and digest")
            if not started <= _time(json.loads(files[companion])["observedAt"]) <= ended:
                raise ValueError(f"{name} network observation is outside its stage")
            if stage != "fetch_all":
                network_info = json.loads(files[name])
                if (not isinstance(network_info, dict)
                        or network_id_from_ext_pan_id(network_info.get("extPanId")) != network_id):
                    raise ValueError(f"{name} does not report the selected network")
        rows = json.loads(files[snapshot])
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid CLI snapshot")
    except (ValueError, KeyError, TypeError) as exc:
        raise SyncEvidenceError(f"Invalid {label} capture: {exc}") from exc
    return files, rows, {
        "directory": str(directory.resolve()),
        "startedAt": meta["fetch_all_started_utc"],
        "endedAt": meta["fetch_all_ended_utc"],
        "snapshotSha256": _digest(files[snapshot]),
    }


def _capture_observations(rows):
    present, identities, qualified, conflicts = set(), {}, {}, set()
    parents = tables = 0
    for row in rows:
        children = row.get("children")
        children = children if isinstance(children, list) else []
        if row.get("type") in ("router", "border router"):
            parents += 1
            tlvs = row.get("tlvResponseValues")
            tables += isinstance(tlvs, str) and "16" in tlvs.split()
        for item in (row, *children):
            if not isinstance(item, dict):
                continue
            try:
                address = normalize_valid_extaddr(item.get("extAddress"))
            except ValueError:
                continue
            present.add(address)
            try:
                eui = _record_eui(item)
            except ValueError:
                conflicts.add(address)
                continue
            if eui is not None:
                identities.setdefault(address, set()).add(eui)
            merge_conflicts = item.get("_merge_conflicts", [])
            if isinstance(merge_conflicts, list) and any(
                isinstance(entry, dict) and entry.get("path") in ("extAddress", "eui", "eui64")
                for entry in merge_conflicts
            ):
                conflicts.add(address)
            history = item.get("tlvResponseHistory")
            if eui is not None and isinstance(history, list) and any(
                isinstance(answer, dict) and answer.get("parseStatus") == "valid"
                and answer.get("finalAnswer") is True
                and answer.get("requestAssociation") == "query-id"
                and isinstance(answer.get("receivedTypeIds"), list)
                and all(tlv in answer["receivedTypeIds"] for tlv in (0, 23))
                and answer.get("malformedTypeIds") == []
                and answer.get("undecodedTypeIds") == []
                for answer in history
            ):
                qualified.setdefault(eui, set()).add(address)
    return present, identities, qualified, conflicts, {"routerRows": parents, "childTables": tables}


def _rekey_preview(records, raw_map, captures, network_id, now, max_age):
    old_files, old_rows, before = _retained_capture(captures[0], "before", network_id, now, max_age)
    new_files, new_rows, after = _retained_capture(captures[1], "after", network_id, now, max_age)
    if _time(before["endedAt"]) >= _time(after["startedAt"]):
        raise SyncEvidenceError("Before and after capture intervals must be strictly ordered")
    old_present, old_ids, old_qualified, old_conflicts, before["coverage"] = _capture_observations(old_rows)
    new_present, new_ids, new_qualified, new_conflicts, after["coverage"] = _capture_observations(new_rows)
    by_address = {}
    by_eui = {}
    for row in records:
        address = _record_extaddr(row)
        for item in (address, *row.get("previousExtAddresses", [])):
            by_address.setdefault(normalize_valid_extaddr(item), []).append(row)
        eui = _record_eui(row)
        if eui is not None:
            by_eui.setdefault(eui, []).append(row)

    candidates = []
    for eui in sorted(old_qualified.keys() & new_qualified.keys()):
        previous = sorted(old_qualified[eui])
        current = sorted(new_qualified[eui])
        before_address = previous[0] if len(previous) == 1 else None
        after_address = current[0] if len(current) == 1 else None
        exact = [row for row in by_address.get(before_address, ())
                 if _record_extaddr(row) == before_address]
        mapped = by_eui.get(eui, []) or exact
        row = mapped[0] if len(mapped) == 1 else None
        primary = _record_extaddr(row) if row is not None else None
        addresses = {*previous, *current} | ({primary} if primary is not None else set())
        state, reason = "ineligible", "unbound-map-eui"
        if (len(previous) != 1 or len(current) != 1
                or any(eui in values and address not in previous for address, values in old_ids.items())
                or any(eui in values and address not in current for address, values in new_ids.items())
                or (before_address != after_address
                    and (after_address in old_present or before_address in new_present))
                or (primary not in (before_address, after_address)
                    and (primary in old_present or primary in new_present))):
            state, reason = "conflict", "observed-address-overlap"
        elif ((old_conflicts | new_conflicts) & addresses
              or any((old_ids.get(address, set()) | new_ids.get(address, set())) - {eui}
                     for address in addresses)):
            state, reason = "conflict", "different-observed-eui"
        elif len(mapped) > 1 or (row is not None and any(
            item is not row for item in by_address.get(before_address, ())
        )):
            state, reason = "conflict", "ambiguous-map-owner"
        elif row is not None:
            if _record_eui(row) not in (None, eui):
                state, reason = "conflict", "different-stored-eui"
            elif before_address == after_address or primary == after_address:
                state, reason = "already-matching", None
            elif by_address.get(after_address) or len(by_address[primary]) != 1:
                state, reason = "conflict", "address-already-owned"
            else:
                state, reason = "rekey", None
        candidate = {
            "id": _candidate_id([primary, previous, current], eui),
            "state": state, "reason": reason, "eui": eui, "extAddress": primary,
            "beforeExtAddresses": previous, "afterExtAddresses": current,
            "newExtAddress": after_address,
            "deviceLabel": (row.get("deviceLabel") or row.get("device_label")) if row else None,
            "comment": row.get("comment") if row else None,
        }
        if state == "rekey":
            candidate["previousExtAddresses"] = [
                primary, *[normalize_valid_extaddr(item) for item in row.get("previousExtAddresses", [])],
            ]
        candidates.append(candidate)
    return {
        "version": 1, "source": "cache", "networkId": network_id,
        "maxEvidenceAgeSeconds": max_age, "mode": "reviewed-map-rekey",
        "retirementEligible": False, "captures": {"before": before, "after": after},
        "fingerprints": {
            "map": _digest(raw_map),
            "inputs": {f"{label}/{name}": _digest(raw)
                       for label, files in (("before", old_files), ("after", new_files))
                       for name, raw in sorted(files.items())},
        },
        "candidates": candidates,
    }


def _preview(data_dir, *, source, network_id, max_evidence_age, keep, now, captures):
    map_path = data_dir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
    raw_map = _read(map_path)
    if raw_map is None:
        raise FileNotFoundError(map_path)
    records = _load_static_records_strict(map_path)
    if _read(map_path) != raw_map:
        raise SyncEvidenceError("map changed during preview")
    if captures is not None:
        return _rekey_preview(records, raw_map, captures, network_id, now, max_evidence_age)
    files, cli_name, cli_mtime = _cache_inputs(data_dir) if source == "cache" else ({}, None, None)
    observations = _rest_observations(files, network_id, now, max_evidence_age)
    direct_rest = {address: set(euis) for address, euis in observations.items()}
    cli_observations = _cli_observations(files, cli_name, cli_mtime, network_id, now, max_evidence_age)
    for address, euis in cli_observations.items():
        observations.setdefault(address, set()).update(euis)
    disagreements = _cache_disagreements(files, network_id)
    roster_euis = {}
    if source == "health-roster":
        # Roster field projection does not establish original same-record
        # binding, capture-time provenance, or qualified absence.
        from td_health_read import HealthReadError, TDHealthReadService

        try:
            service = TDHealthReadService(data_dir)
        except HealthReadError as exc:
            raise SyncEvidenceError(str(exc)) from exc
        devices = []
        offset = 0
        while True:
            try:
                page = service.roster(network_id=network_id, limit=100, offset=offset,
                                      presence="all", read_time=now)
            except HealthReadError as exc:
                raise SyncEvidenceError(str(exc)) from exc
            for device in page["devices"]:
                field = device.get("fields", {}).get("eui", {})
                devices.append({
                    "deviceId": device.get("deviceId"),
                    "eui": {key: field.get(key) for key in
                            ("value", "sourceObservedAt", "sourceFile",
                             "observationId", "conflictState")},
                })
            offset += len(page["devices"])
            if offset >= page["total"]:
                break
            if not page["devices"]:
                raise SyncEvidenceError("incomplete roster read")
        files["roster-projection"] = json.dumps(
            sorted(devices, key=lambda item: item["deviceId"] or ""),
            sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        for device in devices:
            try:
                address = normalize_valid_extaddr(device["deviceId"].removeprefix("extaddr:"))
                eui = normalize_valid_eui(device["eui"]["value"])
                roster_euis.setdefault(address, set()).add(eui)
            except (AttributeError, ValueError, TypeError):
                continue

    owners = {}
    for row in records:
        eui = _record_eui(row)
        if eui:
            owners.setdefault(eui, []).append(_record_extaddr(row))
    for address, euis in observations.items():
        for eui in euis:
            owners.setdefault(eui, []).append(address)
    for address, euis in disagreements.items():
        for eui in euis:
            owners.setdefault(eui, []).append(address)
    observed_owners = {}
    for address, euis in direct_rest.items():
        for eui in euis:
            observed_owners.setdefault(eui, set()).add(address)
    candidates = []
    for row in records:
        address = _record_extaddr(row)
        stored = _record_eui(row)
        seen = observations.get(address, set())
        eui = stored or (next(iter(seen)) if len(seen) == 1 else None)
        state, reason = "ineligible", "no-eui" if not eui else "unproven-succession"
        unqualified = disagreements.get(address, set()) | roster_euis.get(address, set())
        if eui is None and unqualified:
            reason = "unverified-observation"
        conflicting_cache = unqualified
        if (len(seen) > 1 or stored and seen and stored not in seen
                or eui and any(value != eui for value in conflicting_cache)):
            state, reason = "conflict", "different-observed-eui"
        elif eui and len(observed_owners.get(eui, set())) > 1:
            state, reason = "conflict", "same-capture-eui-collision"
        elif eui and len(set(owners.get(eui, []))) > 1:
            # Multiple addresses alone cannot distinguish succession from collision.
            state, reason = "ineligible", "unproven-succession"
        elif not stored and eui and eui in seen:
            state, reason = "fill-eui", None
        candidates.append({
            "id": _candidate_id(address, eui), "state": state, "reason": reason,
            "extAddress": address, "eui": eui,
            "evidenceSources": [
                name for name, source_rows in (
                    (cli_name, cli_observations),
                    (OTBR_RESTAPI_DIAGNOSTICS_FETCH_ALL_OUTCOME_FILENAME, direct_rest),
                )
                if eui in source_rows.get(address, ())
            ],
            "unverifiedEuis": sorted(unqualified - seen),
            "deviceLabel": row.get("deviceLabel") or row.get("device_label"),
            "comment": row.get("comment"),
        })
    candidates.sort(key=lambda item: (item["extAddress"], item["id"]))
    return {
        "version": 1, "source": source, "networkId": network_id,
        "maxEvidenceAgeSeconds": max_evidence_age, "keep": sorted(keep),
        "fingerprints": {
            "map": _digest(raw_map),
            "cliMtimeNs": cli_mtime,
            "inputs": {name: _digest(value) if value is not None else None
                       for name, value in sorted(files.items())},
        },
        "candidates": candidates,
    }


def sync_eui(data_dir, *, source="cache", network_id, max_evidence_age=604800,
             keep=(), apply=False, from_preview=None, select=(), all_eligible=False,
             before_capture=None, after_capture=None, clock=None):
    """Return a preview, or validate and apply selected fills or reviewed moves.

    ``max_evidence_age`` is seconds; ``clock`` is an optional UTC datetime
    callable. Apply preserves exact bytes of untouched row objects.
    """
    data_dir = Path(data_dir)
    if source not in ("cache", "health-roster"):
        raise ValueError("invalid sync source")
    captures = None
    if before_capture is not None or after_capture is not None:
        if before_capture is None or after_capture is None or source != "cache":
            raise ValueError("both capture directories are required with --source cache")
        if all_eligible:
            raise ValueError("reviewed rekeys require explicit --select IDs")
        captures = (before_capture, after_capture)
    if not isinstance(network_id, str) or not network_id.startswith("extpan:"):
        raise ValueError("network_id must be extpan:<16-hex>")
    if network_id_from_ext_pan_id(network_id[7:]) != network_id:
        raise ValueError("network_id must be canonical")
    if (isinstance(max_evidence_age, bool)
            or not isinstance(max_evidence_age, (int, float))
            or not math.isfinite(max_evidence_age) or max_evidence_age <= 0):
        raise ValueError("max_evidence_age must be positive seconds")
    keep = tuple(normalize_valid_extaddr(value) for value in keep)
    if keep:
        raise SyncEvidenceError("--keep is not available until qualified succession is supported")
    if apply != (from_preview is not None):
        raise ValueError("--apply requires --from-preview, and vice versa")
    if (select or all_eligible) and not apply:
        raise ValueError("selection requires --apply")
    if apply and (bool(select) == bool(all_eligible)):
        raise ValueError("choose --select or --all-eligible")
    if len(select) != len(set(select)):
        raise ValueError("duplicate candidate selection")
    now = clock() if clock else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    args = dict(source=source, network_id=network_id, max_evidence_age=max_evidence_age,
                keep=keep, now=now, captures=captures)
    if not apply:
        return _preview(data_dir, **args)
    reviewed = json.loads(Path(from_preview).read_bytes())
    with _map_lock(data_dir / EXTADDR_DEVICE_LABEL_MAP_FILENAME):
        current = _preview(data_dir, **args)
        if reviewed != current:
            raise SyncEvidenceError("reviewed preview no longer matches current inputs or decisions")
        eligible = {c["id"]: c for c in current["candidates"] if c["state"] in ("fill-eui", "rekey")}
        selected = set(eligible) if all_eligible else set(select)
        if not selected <= eligible.keys():
            raise SyncEvidenceError("selection includes an unknown or ineligible candidate")
        if not selected:
            return {**current, "applied": []}
        path = data_dir / EXTADDR_DEVICE_LABEL_MAP_FILENAME
        raw = path.read_bytes()
        before = _load_static_records_strict(path)
        after = [dict(row) for row in before]
        selected_by_address = {eligible[item]["extAddress"]: eligible[item] for item in selected}
        for row in after:
            candidate = selected_by_address.get(_record_extaddr(row))
            if candidate:
                if candidate["state"] == "rekey":
                    row["extAddress"] = candidate["newExtAddress"]
                    for alias in ("extaddr", "Extended MAC"):
                        if alias in row:
                            row[alias] = row["extAddress"]
                    row["previousExtAddresses"] = candidate["previousExtAddresses"]
                row["eui"] = candidate["eui"]
                row["lastUpdated"] = _timestamp(lambda: now)
        _validate_records(after, final=True)
        serialized = _serialize_preserving_rows(raw, before, after)
        if _preview(data_dir, **args) != current:
            raise SyncEvidenceError("inputs changed during apply")
        _save_map(after, path, serialized=serialized)
        return {**current, "applied": sorted(selected)}
