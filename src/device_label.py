#!/usr/bin/env python3
"""
Merge new extaddr entries from merge input fileinto static extaddr file.

This script:
1. Loads both the merge input fileand static extaddr file
2. Finds extaddr entries in the merge input filethat are missing from the static extaddr file
3. Adds the missing entries to the static extaddr file in sorted order by extaddr
4. Writes the updated static extaddr file back to disk
"""

import os
import sys
import argparse
import fcntl
import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from td_const import (
    EXTADDR_DEVICE_LABEL_MAP_FILENAME,
    MDNS_SCOPES_BR_FILENAME,
    MERGED_TOPOLOGY_ALL_FILENAME,
    OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
    TD_DATA_DIR_ARG_HELP,
)
from util_data import (
    TDRequiredInputMissingError,
    data_file_path,
    require_existing_input_file,
    resolve_data_dir,
    save_json_atomic,
    save_text_atomic,
)
from extaddr_device_label_map import EXTADDR_FIELD_ALIASES, load_extaddr_device_label_map

EXTADDR_PATTERN = re.compile(r"^[0-9a-fA-F]{16}$")
DEVICE_LABEL_MAX_LENGTH = 128
MAP_LOCK_TIMEOUT = 5.0


class ExtaddrNotFoundError(LookupError):
    """Raised when a requested extAddress is not present in the static map."""


class MapBusyError(TimeoutError):
    """Raised when another map writer holds the lock too long."""


def normalize_valid_eui(value):
    if not isinstance(value, str):
        raise ValueError("eui must be a string")
    normalized = value.strip().replace(":", "").replace("-", "").lower()
    if not EXTADDR_PATTERN.fullmatch(normalized) or normalized == "0" * 16:
        raise ValueError("eui must be a nonzero 16-digit hexadecimal value")
    return normalized


def validate_device_label_comment(value):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("comment must be a string of at most 512 characters")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("comment must not contain control characters")


def _record_extaddr(record):
    return normalize_valid_extaddr(
        record.get("extAddress") or record.get("extaddr") or record.get("Extended MAC")
    )


def _record_eui(record):
    values = [normalize_valid_eui(record[key]) for key in ("eui", "eui64") if key in record]
    if len(set(values)) > 1:
        raise ValueError("conflicting eui and eui64 values")
    return values[0] if values else None


def _validate_records(records, *, final=False):
    if not isinstance(records, list):
        raise ValueError("static extAddress map must contain a JSON list")
    addresses = set()
    euis = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"static map entry {index} must be a JSON object")
        primary = _record_extaddr(record)
        normalize_valid_device_label(record.get("deviceLabel") or record.get("device_label"))
        eui = _record_eui(record)
        if "lastUpdated" in record:
            stamp = record["lastUpdated"]
            if not isinstance(stamp, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp
            ):
                raise ValueError("lastUpdated must be UTC ISO 8601 with second precision")
            try:
                datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError as exc:
                raise ValueError("invalid lastUpdated timestamp") from exc
        if "comment" in record:
            validate_device_label_comment(record["comment"])
        history = record.get("previousExtAddresses", [])
        if not isinstance(history, list):
            raise ValueError("previousExtAddresses must be a list")
        history = [normalize_valid_extaddr(value) for value in history]
        if final:
            if eui is not None and eui in euis:
                raise ValueError(f"duplicate eui {eui}; use device-label --sync-eui")
            if eui is not None:
                euis.add(eui)
            for address in [primary, *history]:
                if address in addresses:
                    raise ValueError(f"duplicate extAddress ownership: {address}")
                addresses.add(address)


@contextmanager
def _map_lock(path, timeout=MAP_LOCK_TIMEOUT):
    path = Path(path).resolve()
    with path.with_name(path.name + ".lock").open("a") as lock_file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MapBusyError("map busy")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _save_map(records, path, *, serialized=None):
    _validate_records(records, final=True)
    path = Path(path)
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=backup.name + ".", delete=False) as out:
                temp_path = Path(out.name)
                with path.open("rb") as source:
                    shutil.copyfileobj(source, out)
            os.replace(temp_path, backup)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    if serialized is None:
        save_json_atomic(records, path)
    else:
        save_text_atomic(serialized, path)


def _timestamp(clock):
    return (clock() if clock else datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def normalize_valid_extaddr(value):
    """Return a validated 16-digit Thread Extended Address in lowercase."""
    if not isinstance(value, str):
        raise ValueError("extAddress must be a string")
    normalized = value.strip().lower()
    if not EXTADDR_PATTERN.fullmatch(normalized):
        raise ValueError("extAddress must be exactly 16 hexadecimal characters")
    return normalized


def normalize_valid_device_label(value):
    """Return a trimmed label after applying the device-label contract."""
    if not isinstance(value, str):
        raise ValueError("deviceLabel must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("deviceLabel must not be blank")
    if len(normalized) > DEVICE_LABEL_MAX_LENGTH:
        raise ValueError(
            f"deviceLabel must be at most {DEVICE_LABEL_MAX_LENGTH} characters"
        )
    if any(unicodedata.category(char) == "Cc" for char in normalized):
        raise ValueError("deviceLabel must not contain control characters")
    return normalized


def _load_static_records_strict(extaddr_json_path, *, allow_missing=False, fingerprints=None):
    """Load map records without dropping fields or accepting ambiguous keys."""
    path = Path(extaddr_json_path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if allow_missing:
            if fingerprints is not None:
                fingerprints["map"] = None
            return []
        raise

    if fingerprints is not None:
        fingerprints["map"] = hashlib.sha256(raw).hexdigest()
    records = json.loads(raw.decode("utf-8"))
    _validate_records(records)
    return records


def read_device_label(extaddr_json_path, extaddr, *, observed_eui=None):
    """Read one device label from the static map without mutating it."""
    normalized_extaddr = normalize_valid_extaddr(extaddr)
    records = _load_static_records_strict(extaddr_json_path)
    addresses = [_record_extaddr(record) for record in records]
    if len(addresses) != len(set(addresses)):
        raise ValueError("duplicate extAddress in static map")
    for record, address in zip(records, addresses):
        if address == normalized_extaddr:
            return _label_result(record)
    historical = [record for record in records if any(
        normalize_valid_extaddr(value) == normalized_extaddr
        for value in record.get("previousExtAddresses", [])
    )]
    if len(historical) == 1:
        return _label_result(historical[0])
    if observed_eui is not None:
        eui = normalize_valid_eui(observed_eui)
        matches = [record for record in records if _record_eui(record) == eui]
        if len(matches) == 1:
            return _label_result(matches[0])
    raise ExtaddrNotFoundError(normalized_extaddr)


def _label_result(record):
    result = {
        "extAddress": _record_extaddr(record),
        "deviceLabel": normalize_valid_device_label(
            record.get("deviceLabel") or record.get("device_label")
        ),
    }
    if (eui := _record_eui(record)) is not None:
        result["eui"] = eui
    result.update({key: record[key] for key in ("comment", "lastUpdated") if key in record})
    return result


def upsert_device_label(
    extaddr_json_path, extaddr, device_label, *, eui=None, observed_eui=None,
    comment=None, yes=False, clock=None,
):
    """Insert or update one label and atomically persist the static map."""
    normalized_extaddr = normalize_valid_extaddr(extaddr)
    normalized_label = normalize_valid_device_label(device_label)
    normalized_eui = normalize_valid_eui(eui) if eui is not None else None
    observed_eui = normalize_valid_eui(observed_eui) if observed_eui is not None else None
    if normalized_eui is not None and observed_eui is not None:
        raise ValueError("--eui and --observed-eui are mutually exclusive")
    if comment is not None:
        validate_device_label_comment(comment)
    with _map_lock(extaddr_json_path):
        return _upsert_device_label_locked(
            extaddr_json_path, normalized_extaddr, normalized_label,
            normalized_eui, observed_eui, comment, yes, clock,
        )


def _upsert_device_label_locked(
    extaddr_json_path, normalized_extaddr, normalized_label, eui, observed_eui,
    comment, yes, clock,
):
    records = _load_static_records_strict(extaddr_json_path, allow_missing=True)
    observed_result = {}
    if observed_eui is not None:
        current = next((row for row in records if _record_extaddr(row) == normalized_extaddr), None)
        current_eui = _record_eui(current) if current is not None else None
        owners = [
            row for row in records
            if _record_extaddr(row) != normalized_extaddr and _record_eui(row) == observed_eui
        ]
        if current_eui is not None:
            observed_result["euiOutcome"] = (
                "unchanged" if current_eui == observed_eui else "skipped-different"
            )
        elif owners:
            if len(owners) != 1:
                raise ValueError(f"multiple map rows own observed EUI {observed_eui}")
            owner = _label_result(owners[0])
            observed_result.update(
                euiOutcome="skipped-owned-by",
                euiOwner={key: owner[key] for key in ("extAddress", "deviceLabel")},
            )
        else:
            eui = observed_eui
            observed_result["euiOutcome"] = "set"
    if eui is not None and any(
        _record_extaddr(record) != normalized_extaddr and _record_eui(record) == eui
        for record in records
    ):
        raise ValueError(f"duplicate eui {eui}; use device-label --sync-eui")

    operation = "inserted"
    changed = False
    for record in records:
        record_extaddr = _record_extaddr(record)
        if record_extaddr != normalized_extaddr:
            continue
        current_eui = _record_eui(record)
        if eui is not None and current_eui is not None and eui != current_eui and not yes:
            raise ValueError("replacing an existing eui requires --yes or --apply")
        label_key = "deviceLabel" if record.get("deviceLabel") else "device_label"
        if normalize_valid_device_label(record[label_key]) != normalized_label:
            record[label_key] = normalized_label
            changed = True
        if eui is not None and eui != current_eui:
            record.pop("eui64", None)
            record["eui"] = eui
            changed = True
        if comment is not None:
            if comment == "":
                if "comment" in record:
                    del record["comment"]
                    changed = True
            elif record.get("comment") != comment:
                record["comment"] = comment
                changed = True
        operation = "updated"
        break
    else:
        record = {"extAddress": normalized_extaddr, "deviceLabel": normalized_label}
        if eui is not None:
            record["eui"] = eui
        if comment:
            record["comment"] = comment
        records.append(record)
        changed = True

    if not changed:
        if observed_eui is not None:
            _validate_records(records, final=True)
        return {**_label_result(record), "operation": operation, **observed_result}

    record["lastUpdated"] = _timestamp(clock)

    records.sort(
        key=lambda record: normalize_valid_extaddr(
            record.get("extAddress")
            or record.get("extaddr")
            or record.get("Extended MAC")
        )
    )
    _save_map(records, extaddr_json_path)
    return {**_label_result(record), "operation": operation, **observed_result}

def _is_valid_label(value):
    return isinstance(value, str) and bool(value.strip())


def strip_dns_sd_service_suffix(name, scope):
    """Strip only the DNS-SD suffix declared by the record."""
    if not isinstance(name, str):
        return ""
    name = name.strip()
    if not isinstance(scope, str):
        return name
    scope = scope.strip().removesuffix(".")
    if not re.fullmatch(r"_[A-Za-z0-9-]+\._(?:udp|tcp)\.local", scope, re.IGNORECASE):
        return name
    suffix = "." + scope
    bare = name.removesuffix(".")
    if bare.lower() == scope.lower():
        return ""
    return bare[:-len(suffix)].strip() if bare.lower().endswith(suffix.lower()) else name


def merge_extaddr_files(
    extaddr_json_path,
    merge_input_file_path,
    merge_name_override=False,
    fallback_device_label_prefix=None,
    *,
    clock=None,
    dry_run=False,
    fingerprints=None,
):
    """
    Merge missing extaddr entries from merge input file into static extaddr file.
    
    Args:
        extaddr_json_path: Path to td-static-extaddr-device-label.json
        merge_input_file_path: Path to thread-networkdiagnostic-topology-rloc16-extaddr-device_label.json
        merge_name_override: If True, replace static Unknown labels with merge input name when available
        fallback_device_label_prefix: Optional prefix for labels generated from extaddr
    
    Returns:
        Tuple of (num_added, added_entries, num_overridden, overridden_entries)
    """
    arguments = (extaddr_json_path, merge_input_file_path, merge_name_override,
                 fallback_device_label_prefix, clock)
    if dry_run:
        return _merge_extaddr_files(*arguments, dry_run=True, fingerprints=fingerprints)
    with _map_lock(extaddr_json_path):
        return _merge_extaddr_files(*arguments, dry_run=False)


def _merge_extaddr_files(
    extaddr_json_path, merge_input_file_path, merge_name_override,
    fallback_device_label_prefix, clock, *, dry_run, fingerprints=None,
):
    static_data = _load_static_records_strict(
        extaddr_json_path, allow_missing=True, fingerprints=fingerprints
    )
    if static_data:
        logging.info(
            "Loaded %d entries from static extaddr file: %s",
            len(static_data),
            extaddr_json_path,
        )
    else:
        logging.warning(
            "No valid entries found in static extaddr file: %s", extaddr_json_path)

    static_records_by_extaddr = {
        normalize_valid_extaddr(
            record.get("extAddress")
            or record.get("extaddr")
            or record.get("Extended MAC")
        ): record
        for record in static_data
    }
    static_extaddrs = set(static_records_by_extaddr)
    static_extaddrs.update(
        normalize_valid_extaddr(address)
        for record in static_data
        for address in record.get("previousExtAddresses", [])
    )

    try:
        # Short circuit if merge input file does not exist
        if not os.path.exists(merge_input_file_path):
            logging.error(f"Merge input file does not exist: {merge_input_file_path}")
            return 0, [], 0, []

        input_bytes = Path(merge_input_file_path).read_bytes()
        if fingerprints is not None:
            fingerprints["input"] = hashlib.sha256(input_bytes).hexdigest()
        merge_input_data = json.loads(input_bytes.decode("utf-8"))
        logging.info(f"Loaded {len(merge_input_data)} entries from merge input file: {merge_input_file_path}")
    except Exception as e:
        logging.error(f"Failed to load merge input file: {merge_input_file_path}: {e}")
        return 0, [], 0, []
    
    # Build merge input entries dict, skipping items without required fields.
    # Prefer a source label, then name, then the optional generated fallback.
    merge_input_entries = {}
    merge_input_names_by_extaddr = {}
    for i, item in enumerate(merge_input_data):
        if item.get('scope') == '_trel._udp.local.':
            continue

        raw_extaddr = next(
            (item[field_name] for field_name in EXTADDR_FIELD_ALIASES if item.get(field_name)),
            None,
        )
        if raw_extaddr is None:
            logging.warning(
                "Merge input entry %s missing an extended-address field: %s",
                i,
                json.dumps(item, indent=4),
            )
            continue
        try:
            extaddr = normalize_valid_extaddr(raw_extaddr)
        except ValueError:
            logging.warning(
                "Merge input entry %s has invalid extended address: %r",
                i,
                raw_extaddr,
            )
            continue

        device_label = item.get('deviceLabel') or item.get('device_label')
        name = strip_dns_sd_service_suffix(item.get('name'), item.get('scope'))

        if _is_valid_label(name):
            merge_input_names_by_extaddr[extaddr] = name.strip()

        if _is_valid_label(device_label):
            merge_input_entries[extaddr] = device_label.strip()
            continue
        if _is_valid_label(name):
            merge_input_entries[extaddr] = merge_input_names_by_extaddr[extaddr]
            continue

        if fallback_device_label_prefix is not None:
            merge_input_entries[extaddr] = f"{fallback_device_label_prefix}-{extaddr}"
            continue

        logging.warning(
            "Merge input entry %s (extaddr=%s) missing usable 'device_label' and 'name' fields",
            i,
            extaddr,
        )
    
    # Find missing extaddrs
    missing_extaddrs = set(merge_input_entries.keys()) - static_extaddrs
    
    # Optionally replace static Unknown labels with merge input name for matching extaddr entries.
    overridden_entries = []
    if merge_name_override:
        for extaddr, item in static_records_by_extaddr.items():
            label_key = "deviceLabel" if "deviceLabel" in item else "device_label"
            static_label = item.get(label_key, "")
            if 'unknown' not in static_label.lower():
                continue

            name = merge_input_names_by_extaddr.get(extaddr)
            if not _is_valid_label(name):
                continue

            name = name.strip()
            if static_label != name:
                old_label = static_label
                item[label_key] = name
                item["lastUpdated"] = _timestamp(clock)
                overridden_entries.append(
                    {
                        "extaddr": extaddr,
                        "old_device_label": old_label,
                        "new_device_label": name,
                    }
                )

    if not missing_extaddrs and not overridden_entries:
        return 0, [], 0, []
    
    # Create entries for missing extaddrs
    added_entries = []
    for extaddr in sorted(missing_extaddrs):
        new_entry = {
            "extaddr": extaddr,
            "device_label": merge_input_entries[extaddr]
        }
        added_entries.append(new_entry)
    
    static_data.extend(
        {
            "extAddress": entry["extaddr"],
            "deviceLabel": entry["device_label"],
            "lastUpdated": _timestamp(clock),
        }
        for entry in added_entries
    )
    static_data.sort(
        key=lambda item: normalize_valid_extaddr(
            item.get("extAddress")
            or item.get("extaddr")
            or item.get("Extended MAC")
        )
    )
    
    # Write updated data back to static file
    if dry_run:
        _validate_records(static_data, final=True)
    else:
        _save_map(static_data, extaddr_json_path)
        logging.debug("Saved extaddr data into %s as JSON:\n%s",
                      extaddr_json_path, json.dumps(static_data, indent=4))
    return len(added_entries), added_entries, len(overridden_entries), overridden_entries


def main(argv=None):
    """Main entry point."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        prog='td_cli device-label',
        description='Maintain the static Thread device label map.',
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--merge-mdns-br',
        action='store_true',
        help=f'Use {MDNS_SCOPES_BR_FILENAME} instead of the default merge input file',
    )
    group.add_argument(
        '--merge-topology-all',
        action='store_true',
        help=f'Use {MERGED_TOPOLOGY_ALL_FILENAME} instead of the default merge input file',
    )
    operation_group = parser.add_mutually_exclusive_group()
    operation_group.add_argument(
        '--read-extaddr',
        metavar='EXTADDR',
        help='Read one deviceLabel by 16-digit extAddress as JSON',
    )
    operation_group.add_argument(
        '--update-extaddr',
        metavar='EXTADDR',
        help='Update or insert one deviceLabel by 16-digit extAddress',
    )
    operation_group.add_argument('--sync-eui', action='store_true',
                                 help='Preview changes backed by recorded EUI evidence')
    operation_group.add_argument('--suggest-ha-matter', action='store_true',
                                 help='Preview names from cached HA Matter NodeLabel attributes')
    operation_group.add_argument('--suggest-hap', type=Path, metavar='CAPTURE_DIR',
                                 help='Preview names from a verified paired HAP and OTBR capture')
    operation_group.add_argument('--compare-eve', type=Path, metavar='CAPTURE_DIR',
                                 help='Compare native Eve names to a verified OTBR capture for manual review')
    parser.add_argument(
        '--device-label',
        help='Device label for --update-extaddr',
    )
    eui_group = parser.add_mutually_exclusive_group()
    eui_group.add_argument('--eui', '--eui64', help='EUI-64 for --update-extaddr')
    eui_group.add_argument('--observed-eui', help='Record EUI-64 only if not already stored or owned')
    parser.add_argument('--comment', help='Comment for --update-extaddr; empty clears it')
    parser.add_argument('--yes', action='store_true', help='Allow replacing an existing EUI')
    parser.add_argument('--apply', action='store_true',
                        help='Apply a reviewed sync or allow replacing an existing EUI')
    parser.add_argument('--source', choices=('cache', 'health-roster'))
    parser.add_argument('--network', metavar='NETWORK_ID')
    parser.add_argument('--max-evidence-age', type=int, metavar='SECONDS')
    parser.add_argument('--before-capture', type=Path, metavar='DIR')
    parser.add_argument('--after-capture', type=Path, metavar='DIR')
    parser.add_argument('--keep', action='append', metavar='EXTADDR')
    parser.add_argument('--from-preview', type=Path, metavar='FILE')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--select', action='append', metavar='ID')
    selection.add_argument('--all-eligible', action='store_true')
    parser.add_argument(
        '--merge-input-file',
        default=OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
        help=f'Merge input file name (default: {OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME})'
    )
    parser.add_argument(
        '--merge_name_override', '--merge-name-override',
        action='store_true',
        help=(
            'If set, replace static Unknown device_label values with merge input name '
            'for matching extaddr entries'
        ),
    )
    parser.add_argument(
        '--fallback-device-label-prefix',
        help=(
            'Generate PREFIX-extaddr labels for merge records with no usable '
            'deviceLabel, device_label, or name'
        ),
    )
    parser.add_argument('--datadir', default=None, help=TD_DATA_DIR_ARG_HELP)
    parser.add_argument('--dry-run', action='store_true', help='Preview a bulk merge without writing')
    args = parser.parse_args(argv)

    single_record_operation = args.read_extaddr is not None or args.update_extaddr is not None
    suggestion = args.suggest_ha_matter or args.suggest_hap is not None or args.compare_eve is not None
    bulk_options_used = (
        args.merge_mdns_br
        or args.merge_topology_all
        or args.merge_input_file != OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
        or args.merge_name_override
        or args.fallback_device_label_prefix is not None
    )
    if (single_record_operation or args.sync_eui or suggestion) and bulk_options_used:
        parser.error('explicit device-label operations cannot be combined with bulk merge options')
    if args.dry_run and (single_record_operation or args.sync_eui or suggestion or args.yes or args.apply):
        parser.error('--dry-run is only for bulk merge previews')
    if args.read_extaddr is not None and args.device_label is not None:
        parser.error('--device-label is only valid with --update-extaddr')
    if args.update_extaddr is not None and args.device_label is None:
        parser.error('--update-extaddr requires --device-label')
    if args.device_label is not None and args.update_extaddr is None:
        parser.error('--device-label requires --update-extaddr')
    suggestion_option = ('--compare-eve' if args.compare_eve is not None else
                         '--suggest-hap' if args.suggest_hap is not None else '--suggest-ha-matter')
    if args.compare_eve is not None and args.apply:
        parser.error(f'{suggestion_option} is preview-only; --apply is not supported')
    if args.update_extaddr is None and (
        args.eui is not None or args.observed_eui is not None or args.comment is not None
        or args.yes or (args.apply and not (args.sync_eui or suggestion))
    ):
        parser.error('--eui, --observed-eui, --comment and --yes require --update-extaddr; --apply requires an applicable operation')
    if args.sync_eui:
        if args.network is None:
            parser.error('--sync-eui requires --network')
        if args.apply:
            if not args.from_preview or not (args.select or args.all_eligible):
                parser.error('--sync-eui --apply requires --from-preview and --select or --all-eligible')
        elif args.from_preview or args.select or args.all_eligible:
            parser.error('--from-preview, --select and --all-eligible require --apply')
    elif suggestion:
        if args.network is None:
            parser.error(f'{suggestion_option} requires --network')
        if any(value is not None for value in (
            args.source, args.max_evidence_age, args.before_capture, args.after_capture,
            args.keep,
        )):
            parser.error(f'{suggestion_option} does not accept EUI sync options')
        if args.all_eligible:
            parser.error(f'{suggestion_option} does not support --all-eligible')
        if args.apply and (args.from_preview is None or not args.select):
            parser.error(f'{suggestion_option} --apply requires --from-preview and explicit --select IDs')
        if not args.apply and (args.from_preview is not None or args.select):
            parser.error('--from-preview and --select require --apply')
    elif any(value is not None for value in (args.source, args.network, args.max_evidence_age,
                                             args.before_capture, args.after_capture,
                                             args.keep, args.from_preview, args.select)) or args.all_eligible:
        parser.error('sync options require --sync-eui')
    if args.fallback_device_label_prefix is not None:
        try:
            normalize_valid_device_label(
                f"{args.fallback_device_label_prefix}-0000000000000000"
            )
        except ValueError as exc:
            parser.error(f'--fallback-device-label-prefix is invalid: {exc}')
    
    # Use datadir
    td_data_dir = resolve_data_dir(data_dir=args.datadir, create_default=not suggestion)

    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

    if suggestion:
        from functools import partial

        from td_device_label_suggestions import apply_name_suggestions, preview_ha_matter_names

        try:
            if args.compare_eve is not None:
                from td_hap_label_suggestions import compare_eve_names

                preview = partial(compare_eve_names, args.compare_eve, extaddr_json_filename, args.network)
            elif args.suggest_hap is not None:
                from td_hap_label_suggestions import preview_hap_names

                preview = partial(preview_hap_names, args.suggest_hap, extaddr_json_filename, args.network)
            else:
                preview = partial(preview_ha_matter_names, td_data_dir, extaddr_json_filename, args.network)
            result = (apply_name_suggestions(extaddr_json_filename, preview, args.from_preview, args.select)
                      if args.apply else preview())
        except MapBusyError as exc:
            print(str(exc), file=sys.stderr)
            return 7
        except (ValueError, OSError) as exc:
            print(f"{suggestion_option} {'apply' if args.apply else 'preview'} failed: {exc}", file=sys.stderr)
            return 5
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.sync_eui:
        from td_device_label_sync import sync_eui

        try:
            options = {}
            if args.max_evidence_age is not None:
                options["max_evidence_age"] = args.max_evidence_age
            result = sync_eui(
                td_data_dir, source=args.source or "cache", network_id=args.network,
                keep=args.keep or (), apply=args.apply, from_preview=args.from_preview,
                before_capture=args.before_capture, after_capture=args.after_capture,
                select=args.select or (), all_eligible=args.all_eligible, **options,
            )
        except MapBusyError as exc:
            print(str(exc), file=sys.stderr)
            return 7
        except FileNotFoundError as exc:
            print(f"Required sync input not found: {exc}", file=sys.stderr)
            return 4
        except (ValueError, TypeError) as exc:
            print(f"Invalid device-label sync: {exc}", file=sys.stderr)
            return 5
        except OSError as exc:
            print(f"Failed to access device-label sync input: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if single_record_operation:
        try:
            if args.read_extaddr is not None:
                result = read_device_label(extaddr_json_filename, args.read_extaddr)
            else:
                result = upsert_device_label(
                    extaddr_json_filename,
                    args.update_extaddr,
                    args.device_label,
                    eui=args.eui,
                    observed_eui=args.observed_eui,
                    comment=args.comment,
                    yes=args.yes or args.apply,
                )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except FileNotFoundError as exc:
            print(f"Static extAddress map not found: {exc}", file=sys.stderr)
            return 4
        except ExtaddrNotFoundError as exc:
            print(f"extAddress not found: {exc}", file=sys.stderr)
            return 6
        except MapBusyError as exc:
            print(str(exc), file=sys.stderr)
            return 7
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            print(f"Invalid static extAddress map or argument: {exc}", file=sys.stderr)
            return 5
        except OSError as exc:
            print(f"Failed to access static extAddress map: {exc}", file=sys.stderr)
            return 3

    # Choose merge input file from flags or args
    if args.merge_mdns_br:
        merge_input_file = Path(MDNS_SCOPES_BR_FILENAME)
    elif args.merge_topology_all:
        merge_input_file = Path(MERGED_TOPOLOGY_ALL_FILENAME)
    else:
        merge_input_file = Path(args.merge_input_file)

    if not merge_input_file.is_file():
        # try using the specified merge input file as a filename under data directory
        merge_input_file = data_file_path(
            merge_input_file, td_data_dir
        )
    
    # Perform merge
    try:       
        # Optional: static extaddr file 
        # mDNS br records will have names for Thread Border Routers
        
        require_existing_input_file(
            Path(merge_input_file),
            command_path="merge-extaddr-map",
            data_dir=td_data_dir,
            classification="required",
            action="fail code=4",
        )

        fingerprints = {} if args.dry_run else None
        num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
            extaddr_json_filename,
            merge_input_file,
            merge_name_override=args.merge_name_override,
            fallback_device_label_prefix=args.fallback_device_label_prefix,
            dry_run=args.dry_run,
            fingerprints=fingerprints,
        )
        if fingerprints is not None:
            print(f"Snapshot SHA-256: {json.dumps(fingerprints, sort_keys=True)}")
        
        if num_added == 0 and num_overridden == 0:
            print("No missing extaddr entries found. No changes made.")
            return 0

        if num_added > 0:
            print(f"{'Would add' if args.dry_run else 'Added'} {num_added} new extaddr entry/entries:")
            for entry in added_entries:
                print(f"  {entry['extaddr']}: {entry['device_label']}")

        if num_overridden > 0:
            print(f"{'Would update' if args.dry_run else 'Updated'} {num_overridden} existing Unknown device_label value(s) using merge input name:")
            for entry in overridden_entries:
                print(
                    f"  {entry['extaddr']}: {entry['old_device_label']} -> {entry['new_device_label']}"
                )
        
        return 0
    
    except TDRequiredInputMissingError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except MapBusyError as exc:
        print(str(exc), file=sys.stderr)
        return 7
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"Invalid payload while merging extaddr map: {exc}", file=sys.stderr)
        return 5
    except Exception as e:
        print(f"Error during merge: {e}", file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
