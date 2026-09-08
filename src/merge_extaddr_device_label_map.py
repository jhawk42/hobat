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
import json
import logging
import re
import unicodedata
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
)
from extaddr_device_label_map import EXTADDR_FIELD_ALIASES, load_extaddr_device_label_map

EXTADDR_PATTERN = re.compile(r"^[0-9a-fA-F]{16}$")
DEVICE_LABEL_MAX_LENGTH = 128


class ExtaddrNotFoundError(LookupError):
    """Raised when a requested extAddress is not present in the static map."""


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


def _load_static_records_strict(extaddr_json_path, *, allow_missing=False):
    """Load map records without dropping fields or accepting ambiguous keys."""
    path = Path(extaddr_json_path)
    if not path.is_file():
        if allow_missing:
            return []
        raise FileNotFoundError(path)

    with path.open(encoding="utf-8") as file_handle:
        records = json.load(file_handle)
    if not isinstance(records, list):
        raise ValueError("static extAddress map must contain a JSON list")

    seen_extaddrs = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"static map entry {index} must be a JSON object")
        raw_extaddr = (
            record.get("extAddress")
            or record.get("extaddr")
            or record.get("Extended MAC")
        )
        extaddr = normalize_valid_extaddr(raw_extaddr)
        if extaddr in seen_extaddrs:
            raise ValueError(f"duplicate extAddress in static map: {extaddr}")
        seen_extaddrs.add(extaddr)

        raw_label = record.get("deviceLabel") or record.get("device_label")
        normalize_valid_device_label(raw_label)

    return records


def read_device_label(extaddr_json_path, extaddr):
    """Read one device label from the static map without mutating it."""
    normalized_extaddr = normalize_valid_extaddr(extaddr)
    records = _load_static_records_strict(extaddr_json_path)
    for record in records:
        record_extaddr = normalize_valid_extaddr(
            record.get("extAddress")
            or record.get("extaddr")
            or record.get("Extended MAC")
        )
        if record_extaddr == normalized_extaddr:
            device_label = normalize_valid_device_label(
                record.get("deviceLabel") or record.get("device_label")
            )
            return {
                "extAddress": normalized_extaddr,
                "deviceLabel": device_label,
            }
    raise ExtaddrNotFoundError(normalized_extaddr)


def upsert_device_label(extaddr_json_path, extaddr, device_label):
    """Insert or update one label and atomically persist the static map."""
    normalized_extaddr = normalize_valid_extaddr(extaddr)
    normalized_label = normalize_valid_device_label(device_label)
    records = _load_static_records_strict(extaddr_json_path, allow_missing=True)

    operation = "inserted"
    for record in records:
        record_extaddr = normalize_valid_extaddr(
            record.get("extAddress")
            or record.get("extaddr")
            or record.get("Extended MAC")
        )
        if record_extaddr != normalized_extaddr:
            continue
        if "deviceLabel" in record and "device_label" not in record:
            record["deviceLabel"] = normalized_label
        else:
            record["device_label"] = normalized_label
        operation = "updated"
        break
    else:
        records.append(
            {"extaddr": normalized_extaddr, "device_label": normalized_label}
        )

    records.sort(
        key=lambda record: normalize_valid_extaddr(
            record.get("extAddress")
            or record.get("extaddr")
            or record.get("Extended MAC")
        )
    )
    save_json_atomic(records, extaddr_json_path)
    return {
        "extAddress": normalized_extaddr,
        "deviceLabel": normalized_label,
        "operation": operation,
    }

def _is_valid_label(value):
    return isinstance(value, str) and bool(value.strip())


def merge_extaddr_files(
    extaddr_json_path,
    merge_input_file_path,
    merge_name_override=False,
    fallback_device_label_prefix=None,
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
    static_data = _load_static_records_strict(extaddr_json_path, allow_missing=True)
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

    try:
        # Short circuit if merge input file does not exist
        if not os.path.exists(merge_input_file_path):
            logging.error(f"Merge input file does not exist: {merge_input_file_path}")
            return 0, [], 0, []

        # Load merge input file
        with open(merge_input_file_path, 'r') as f:
            merge_input_data = json.load(f)
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
        name = item.get('name')

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
    
    static_data.extend(added_entries)
    static_data.sort(
        key=lambda item: normalize_valid_extaddr(
            item.get("extAddress")
            or item.get("extaddr")
            or item.get("Extended MAC")
        )
    )
    
    # Write updated data back to static file
    save_json_atomic(static_data, extaddr_json_path)
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
        description='Merge new extaddr entries from merge input file into static extaddr file.'
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
    parser.add_argument(
        '--device-label',
        help='Device label for --update-extaddr',
    )
    parser.add_argument(
        '--merge-input-file',
        default=OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME,
        help=f'Merge input file name (default: {OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME})'
    )
    parser.add_argument(
        '--merge_name_override',
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
    args = parser.parse_args(argv)

    single_record_operation = args.read_extaddr is not None or args.update_extaddr is not None
    bulk_options_used = (
        args.merge_mdns_br
        or args.merge_topology_all
        or args.merge_input_file != OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME
        or args.merge_name_override
        or args.fallback_device_label_prefix is not None
    )
    if single_record_operation and bulk_options_used:
        parser.error('single-record operations cannot be combined with bulk merge options')
    if args.read_extaddr is not None and args.device_label is not None:
        parser.error('--device-label is only valid with --update-extaddr')
    if args.update_extaddr is not None and args.device_label is None:
        parser.error('--update-extaddr requires --device-label')
    if args.device_label is not None and args.update_extaddr is None:
        parser.error('--device-label requires --update-extaddr')
    if args.fallback_device_label_prefix is not None:
        try:
            normalize_valid_device_label(
                f"{args.fallback_device_label_prefix}-0000000000000000"
            )
        except ValueError as exc:
            parser.error(f'--fallback-device-label-prefix is invalid: {exc}')
    
    # Use datadir
    td_data_dir = resolve_data_dir(data_dir=args.datadir)

    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

    if single_record_operation:
        try:
            if args.read_extaddr is not None:
                result = read_device_label(extaddr_json_filename, args.read_extaddr)
            else:
                result = upsert_device_label(
                    extaddr_json_filename,
                    args.update_extaddr,
                    args.device_label,
                )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        except FileNotFoundError as exc:
            print(f"Static extAddress map not found: {exc}", file=sys.stderr)
            return 4
        except ExtaddrNotFoundError as exc:
            print(f"extAddress not found: {exc}", file=sys.stderr)
            return 6
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            print(f"Invalid static extAddress map or argument: {exc}", file=sys.stderr)
            return 5
        except OSError as exc:
            print(f"Failed to access static extAddress map: {exc}", file=sys.stderr)
            return 3

    # Determine file paths relative to this script
    script_dir = Path(__file__).parent

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

        num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
            extaddr_json_filename,
            merge_input_file,
            merge_name_override=args.merge_name_override,
            fallback_device_label_prefix=args.fallback_device_label_prefix,
        )
        
        if num_added == 0 and num_overridden == 0:
            print("No missing extaddr entries found. No changes made.")
            return 0

        if num_added > 0:
            print(f"Added {num_added} new extaddr entry/entries:")
            for entry in added_entries:
                print(f"  {entry['extaddr']}: {entry['device_label']}")

        if num_overridden > 0:
            print(f"Updated {num_overridden} existing Unknown device_label value(s) using merge input name:")
            for entry in overridden_entries:
                print(
                    f"  {entry['extaddr']}: {entry['old_device_label']} -> {entry['new_device_label']}"
                )
        
        return 0
    
    except TDRequiredInputMissingError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"Invalid payload while merging extaddr map: {exc}", file=sys.stderr)
        return 5
    except Exception as e:
        print(f"Error during merge: {e}", file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
