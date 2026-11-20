"""System administration command line interface."""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.client import HTTPException
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from td_system_backups import create_backup, restore_backup
from td_system_database import DatabaseRepackError, repack_database
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
    restore.add_argument("--yes", "--apply", action="store_true")
    restore.add_argument("--json", action="store_true", dest="json_output")
    database = commands.add_parser(
        "database", description="Hobat SQLite database maintenance."
    )
    database_actions = database.add_subparsers(
        dest="database_action", required=True
    )
    database_actions.add_parser(
        "repack", help="Repack the Hobat SQLite database."
    )
    device = commands.add_parser("device", description="Host device diagnostic commands.")
    device_actions = device.add_subparsers(dest="device_action", required=True)
    ping = device_actions.add_parser("ping", description="Probe one literal IP address.")
    ping.add_argument("--address", required=True, metavar="IP")
    ping.add_argument("--family", choices=("auto", "ipv4", "ipv6"), default="auto")
    ping.add_argument("--attempts", type=int, default=1)
    ping.add_argument("--timeout", type=float, default=5.0, metavar="SECONDS")
    ping.add_argument("--deadline", type=float, default=30.0, metavar="SECONDS")
    scheduler = commands.add_parser(
        "scheduler", description="Manage the scheduler owned by a remote server."
    )
    scheduler.add_argument("--datadir", default=argparse.SUPPRESS)
    scheduler_actions = scheduler.add_subparsers(dest="scheduler_action", required=True)
    for action in ("status", "list", "run-now", "pause", "resume", "cancel"):
        command = scheduler_actions.add_parser(action)
        command.add_argument("--datadir", default=argparse.SUPPRESS)
        if action == "cancel":
            command.add_argument("job_id", metavar="JOB_ID")
        command.add_argument("--server-url", required=True, metavar="URL")
        command.add_argument("--json", action="store_true", dest="json_output")
        if action == "run-now":
            command.add_argument("--apply", action="store_true", required=True)
            command.add_argument("--quick", action="store_true")
    return parser


class SchedulerCLIError(ValueError):
    """A remote scheduler request could not be completed."""


def _scheduler_base_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in {"http", "https"} and parts.hostname
            and parts.username is None and parts.password is None
            and not parts.query and not parts.fragment
            and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        )
        _ = parts.port
    except ValueError:
        valid = False
    if not valid:
        raise SchedulerCLIError("--server-url must be an HTTP(S) URL without credentials, query or fragment")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _scheduler_request(base_url: str, path: str, method: str = "GET",
                       payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        request = Request(base_url + path, data=data, headers=headers, method=method)
        with urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise SchedulerCLIError(f"server returned HTTP {response.status}")
            body = response.read(1024 * 1024 + 1)
    except HTTPError as exc:
        raise SchedulerCLIError(f"server returned HTTP {exc.code}") from exc
    except SchedulerCLIError:
        raise
    except (URLError, OSError, HTTPException, ValueError) as exc:
        raise SchedulerCLIError("server unreachable or request timed out") from exc
    if len(body) > 1024 * 1024:
        raise SchedulerCLIError("server response is too large")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchedulerCLIError("server returned non-JSON data") from exc
    if not isinstance(document, dict):
        raise SchedulerCLIError("server returned an invalid JSON object")
    return document


def _is_scheduler_job(job: dict) -> bool:
    return job.get("kind") == "scheduler" or job.get("task") == "scheduler-nightly"


def _run_scheduler(args: argparse.Namespace) -> int:
    if args.datadir is not None:
        print("Error: --datadir cannot select remote data; the selected server owns the directory.", file=sys.stderr)
        return 2
    try:
        base_url = _scheduler_base_url(args.server_url)
        action = args.scheduler_action
        if action == "status":
            document = _scheduler_request(base_url, "/api/scheduler")
        elif action == "list":
            document = _scheduler_request(base_url, "/api/jobs")
            jobs = document.get("jobs")
            if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
                raise SchedulerCLIError("server returned an invalid jobs list")
            document = {"jobs": [job for job in jobs if _is_scheduler_job(job)]}
        elif action == "run-now":
            print(
                "Warning: run-now performs live collection and purge; an automatic run may follow later today.",
                file=sys.stderr,
            )
            document = _scheduler_request(
                base_url, "/api/scheduler/run", "POST",
                {"quick": True} if args.quick else {},
            )
            if not isinstance(document.get("job_id"), str) or not document["job_id"]:
                raise SchedulerCLIError("server returned an invalid job acceptance")
        elif action in {"pause", "resume"}:
            document = _scheduler_request(
                base_url, "/api/scheduler", "PATCH", {"paused": action == "pause"}
            )
        else:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", args.job_id):
                raise SchedulerCLIError("invalid job ID")
            path = "/api/job/" + args.job_id
            job = _scheduler_request(base_url, path)
            if not _is_scheduler_job(job):
                raise SchedulerCLIError("job is not scheduler-owned")
            document = _scheduler_request(base_url, path, "DELETE")
    except SchedulerCLIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(document, sort_keys=True, indent=None if args.json_output else 2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.system_command == "scheduler":
        return _run_scheduler(args)
    if args.system_command == "device" and args.device_action == "ping":
        document, exit_code = run_ping(
            args.address, args.family, args.attempts, args.timeout, args.deadline
        )
        print(json.dumps(document, sort_keys=True))
        return exit_code
    data_dir = resolve_data_dir(args.datadir)
    if args.system_command == "database" and args.database_action == "repack":
        try:
            database_path = repack_database(data_dir)
        except DatabaseRepackError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Repacked Hobat database at {database_path}")
        return 0
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
