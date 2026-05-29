#!/usr/bin/env python3
"""
Merge new extaddr entries from merge input fileinto static extaddr file.

This script:
1. Loads both the merge input fileand static extaddr file
2. Finds extaddr entries in the merge input filethat are missing from the static extaddr file
3. Adds the missing entries to the static extaddr file in sorted order by extaddr
4. Writes the updated static extaddr file back to disk
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from td_const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic

OTBR_CLI_NETWORKDIAG_FETCH_ALL_FILENAME = 'td-otbr-cli-networkdiag-fetch-all.json'
MDNS_SCOPES_BR_FILENAME = "td-mdns-scopes-br.json"
MERGED_TOPOLOGY_ALL_FILENAME = "td-merged-topology-all.json"

def _is_valid_label(value):
    return isinstance(value, str) and bool(value.strip())


def merge_extaddr_files(extaddr_json_path, merge_input_file_path, merge_name_override=False):
    """
    Merge missing extaddr entries from merge input file into static extaddr file.
    
    Args:
        extaddr_json_path: Path to td-static-extaddr-device-label.json
        merge_input_file_path: Path to thread-networkdiagnostic-topology-rloc16-extaddr-device_label.json
        merge_name_override: If True, replace static Unknown labels with merge input name when available
    
    Returns:
        Tuple of (num_added, added_entries, num_overridden, overridden_entries)
    """
    # Load static extaddr file
    with open(extaddr_json_path, 'r') as f:
        static_data = json.load(f)
    logging.info(f"Loaded {len(static_data)} entries from static extaddr file: {extaddr_json_path}")

    # Load merge input file
    with open(merge_input_file_path, 'r') as f:
        merge_input_data = json.load(f)
    logging.info(f"Loaded {len(merge_input_data)} entries from merge input file: {merge_input_file_path}")   

    # Extract extaddr values
    static_extaddrs = {item['extaddr'] for item in static_data}
    
    # Build merge input entries dict, skipping items without required fields.
    # Prefer device_label; fall back to name when device_label is not usable.
    merge_input_entries = {}
    merge_input_names_by_extaddr = {}
    for i, item in enumerate(merge_input_data):
        if item.get('scope') == '_trel._udp.local.':
            continue

        if 'extaddr' not in item:
            logging.warning(f"Merge input entry {i} missing 'extaddr' field: {item} %s", json.dumps(item, indent=4))
            continue
        extaddr = item['extaddr']
        if not _is_valid_label(extaddr):
            logging.warning(f"Merge input entry {i} has invalid 'extaddr' value: {item.get('extaddr')!r}")
            continue

        device_label = item.get('device_label')
        name = item.get('name')

        if _is_valid_label(name):
            merge_input_names_by_extaddr[extaddr] = name.strip()

        if _is_valid_label(device_label):
            merge_input_entries[extaddr] = device_label.strip()
            continue
        if _is_valid_label(name):
            merge_input_entries[extaddr] = merge_input_names_by_extaddr[extaddr]
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
        for item in static_data:
            extaddr = item.get('extaddr')
            if not _is_valid_label(extaddr):
                continue

            static_label = item.get('device_label', '')
            if not isinstance(static_label, str):
                continue
            if 'unknown' not in static_label.lower():
                continue

            name = merge_input_names_by_extaddr.get(extaddr)
            if not _is_valid_label(name):
                continue

            name = name.strip()
            if item['device_label'] != name:
                old_label = item['device_label']
                item['device_label'] = name
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
    
    # Add entries to static_data in sorted order
    for new_entry in added_entries:
        insert_pos = 0
        for i, item in enumerate(static_data):
            if new_entry['extaddr'] < item['extaddr']:
                insert_pos = i
                break
            insert_pos = i + 1
        static_data.insert(insert_pos, new_entry)
    
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
    args = parser.parse_args(argv)
    
    # Use datadir
    td_data_dir = resolve_data_dir(
        data_dir=parse_datadir_from_argv(argv if argv is not None else sys.argv))

    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

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
    
    # Validate files exist
    if not extaddr_json_filename.exists():
        print(f"Error: Static file not found: {extaddr_json_filename}", file=sys.stderr)
        return 1
    
    if not merge_input_file.exists():
        print(f"Error: Merge input file not found: {merge_input_file}", file=sys.stderr)
        return 1
    
    # Perform merge
    try:
        num_added, added_entries, num_overridden, overridden_entries = merge_extaddr_files(
            extaddr_json_filename,
            merge_input_file,
            merge_name_override=args.merge_name_override,
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
    
    except Exception as e:
        print(f"Error during merge: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
