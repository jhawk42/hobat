"""System administration command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from td_system_backups import create_backup, restore_backup
from td_system_ping import run_ping
from util_data import resolve_data_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="td_cli system", description="Hobat system administration commands."
    )
    parser.add_argument("--datadir", default=None)
    commands = parser.add_subparsers(dest="system_command", required=True)
    backups = commands.add_parser("backups", description="Create or restore backups.")
    actions = backups.add_subparsers(dest="backup_action", required=True)
    create = actions.add_parser("create")
    create.add_argument("--output", required=True, type=Path, metavar="DIRECTORY")
    create.add_argument("--json", action="store_true", dest="json_output")
    restore = actions.add_parser("restore")
    restore.add_argument("--input", required=True, type=Path, metavar="BACKUP")
    restore.add_argument("--yes", action="store_true")
    restore.add_argument("--json", action="store_true", dest="json_output")
    device = commands.add_parser("device", description="Host device diagnostic commands.")
    device_actions = device.add_subparsers(dest="device_action", required=True)
    ping = device_actions.add_parser("ping", description="Probe one literal IP address.")
    ping.add_argument("--address", required=True, metavar="IP")
    ping.add_argument("--family", choices=("auto", "ipv4", "ipv6"), default="auto")
    ping.add_argument("--attempts", type=int, default=1)
    ping.add_argument("--timeout", type=float, default=5.0, metavar="SECONDS")
    ping.add_argument("--deadline", type=float, default=30.0, metavar="SECONDS")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.system_command == "device" and args.device_action == "ping":
        document, exit_code = run_ping(
            args.address, args.family, args.attempts, args.timeout, args.deadline
        )
        print(json.dumps(document, sort_keys=True))
        return exit_code
    data_dir = resolve_data_dir(args.datadir)
    if args.backup_action == "create":
        manifest = create_backup(data_dir, args.output)
        location = args.output.resolve()
    else:
        if not args.yes and input(
            "Replace the complete Hobat data directory from this backup? [y/N] "
        ).strip().lower() != "y":
            print("Restore cancelled.")
            return 0
        manifest = restore_backup(data_dir, args.input)
        location = data_dir
    document = {
        "action": args.backup_action,
        "location": str(location),
        "formatVersion": manifest["formatVersion"],
        "createdAt": manifest["createdAt"],
        "fileCount": len(manifest["files"]),
        "databaseSchemaVersion": manifest["databaseSchemaVersion"],
    }
    if args.json_output:
        print(json.dumps(document, sort_keys=True))
    else:
        verb = "Created" if args.backup_action == "create" else "Restored"
        print(f"{verb} Hobat data backup at {location}")
        print(f"Files: {document['fileCount']}")
        print(f"Database schema: {document['databaseSchemaVersion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
