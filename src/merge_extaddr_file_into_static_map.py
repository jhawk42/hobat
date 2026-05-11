#!/usr/bin/env python3
"""
Merge new extaddr entries from topology file into static extaddr file.

This script:
1. Loads both the topology file and static extaddr file
2. Finds extaddr entries in the topology file that are missing from the static extaddr file
3. Adds the missing entries to the static extaddr file in sorted order by extaddr
4. Writes the updated static extaddr file back to disk
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from const import EXTADDR_DEVICE_LABEL_MAP_FILENAME
from util_data import data_file_path, parse_datadir_from_argv, resolve_data_dir, save_json_atomic


def merge_extaddr_files(extaddr_json_path, topology_file_path):
    """
    Merge missing extaddr entries from topology file into static extaddr file.
    
    Args:
        extaddr_json_path: Path to td-static-extaddr-device-label.json
        topology_file_path: Path to thread-networkdiagnostic-topology-rloc16-extaddr-device_label.json
    
    Returns:
        Tuple of (num_added, added_entries)
    """
    # Load static extaddr file
    with open(extaddr_json_path, 'r') as f:
        static_data = json.load(f)
    logging.info(f"Loaded {len(static_data)} entries from static extaddr file: {extaddr_json_path}")

    # Load topology file
    with open(topology_file_path, 'r') as f:
        topology_data = json.load(f)
    logging.info(f"Loaded {len(topology_data)} entries from topology file: {topology_file_path}")   

    # Extract extaddr values
    static_extaddrs = {item['extaddr'] for item in static_data}
    
    # Build topology entries dict, skipping items without required fields
    topology_entries = {}
    for i, item in enumerate(topology_data):
        if 'extaddr' not in item:
            logging.warning(f"Topology entry {i} missing 'extaddr' field: {item} %s", json.dumps(item, indent=4))
            continue
        if 'device_label' not in item:
            logging.warning(f"Topology entry {i} (extaddr={item.get('extaddr')}) missing 'device_label' field")
            continue
        topology_entries[item['extaddr']] = item['device_label']
    
    # Find missing extaddrs
    missing_extaddrs = set(topology_entries.keys()) - static_extaddrs
    
    if not missing_extaddrs:
        return 0, []
    
    # Create entries for missing extaddrs
    added_entries = []
    for extaddr in sorted(missing_extaddrs):
        new_entry = {
            "extaddr": extaddr,
            "device_label": topology_entries[extaddr]
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
    
    return len(added_entries), added_entries


def main():
    """Main entry point."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Merge new extaddr entries from topology file into static extaddr file.'
    )
    parser.add_argument(
        '--topology-file',
        default='td-otbr-cli-networkdiag-topology.json',
        help='Topology file name (default: td-otbr-cli-networkdiag-topology.json)'
    )
    args = parser.parse_args()
    
    # Use datadir
    td_data_dir = resolve_data_dir(
    datadir_arg=parse_datadir_from_argv(sys.argv))

    extaddr_json_filename = data_file_path(
        EXTADDR_DEVICE_LABEL_MAP_FILENAME, td_data_dir
    )

    # Determine file paths relative to this script
    script_dir = Path(__file__).parent

    # Try using args.topology_file directly as a path
    topology_file = Path(args.topology_file)
    if not topology_file.is_file():
        # try using args.topology_file as a filename under script_dir/data
        topology_file = script_dir / 'data' / args.topology_file  # fallback to script_dir/data
    
    # Validate files exist
    if not extaddr_json_filename.exists():
        print(f"Error: Static file not found: {extaddr_json_filename}", file=sys.stderr)
        return 1
    
    if not topology_file.exists():
        print(f"Error: Topology file not found: {topology_file}", file=sys.stderr)
        return 1
    
    # Perform merge
    try:
        num_added, added_entries = merge_extaddr_files(extaddr_json_filename, topology_file)
        
        if num_added == 0:
            print("No missing extaddr entries found. No changes made.")
            return 0
        
        print(f"Added {num_added} new extaddr entry/entries:")
        for entry in added_entries:
            print(f"  {entry['extaddr']}: {entry['device_label']}")
        
        return 0
    
    except Exception as e:
        print(f"Error during merge: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
