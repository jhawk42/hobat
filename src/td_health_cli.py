"""Command-line interface for cache-only health processing."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from td_health_history import import_expected_roster_from_label_map, network_id_for_dataset
from td_health_manifest import load_health_manifest
from td_health_observation_model import device_id_from_ext_address
from td_health_observation_store import HOBAT_DATABASE_FILENAME
from td_health_policy import load_health_policy
from td_health_processor import ProcessingResult, build_processing_result, process_health
from td_health_roster_mutation import set_cli_roster_device
from td_health_sqlite import SQLiteHealthStore
from td_health_migration import (
    HealthMigrationError,
    HealthMigrationInventoryError,
    history_migration_report,
    inventory_health_history,
    migrate_health_history,
)
from util_data import resolve_data_dir, save_json_atomic


LATEST_REPORT_FILENAME = "td-health-latest.json"
DEFAULT_HEALTH_PURGE_KEEP_DAYS = 30


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="td_cli health",
        description="Thread network health commands.",
    )
    parser.add_argument("--datadir", default=None)
    commands = parser.add_subparsers(dest="health_command", required=True)
    process_dataset = commands.add_parser(
        "process-dataset",
        description="Assess approved cached Thread datasets without live collection.",
    )
    process_dataset.add_argument(
        "--dataset",
        required=True,
        choices=["all", *sorted(load_health_manifest().datasets)],
        help="Approved health-eligible dataset ID, or 'all'.",
    )
    process_dataset.add_argument("--allow-partial", action="store_true")
    process_dataset.add_argument("--dry-run", action="store_true")
    process_dataset.add_argument("--json", action="store_true", dest="json_output")
    process_dataset.add_argument(
        "--export-latest",
        nargs="?",
        const=LATEST_REPORT_FILENAME,
        metavar="FILE",
        help="Write a non-authoritative latest report under the data directory.",
    )
    process_dataset.add_argument(
        "--policy-config-dir",
        type=Path,
        default=None,
        help="Directory containing td-health-policy.json.",
    )
    process_dataset.add_argument(
        "--init-roster-from-label-map",
        action="store_true",
        help="Explicitly import expected extAddress entries from the static label map.",
    )
    process_dataset.add_argument("--roster-list", action="store_true", help="List roster records for this network.")
    process_dataset.add_argument("--roster-device", metavar="EXTADDR", help="Add or update this roster device identity.")
    process_dataset.add_argument("--roster-label", help="Label to store with --roster-device.")
    process_dataset.add_argument(
        "--roster-state",
        choices=("expected", "retired", "intentionally-offline", "intermittent"),
        default=None,
        help="State to set with --roster-device; omitted preserves an existing state.",
    )
    compare = commands.add_parser("compare", description="Compare two stored health assessments.")
    compare.add_argument("--before-assessment", required=True)
    compare.add_argument("--after-assessment", required=True)
    compare.add_argument("--dry-run", action="store_true")
    compare.add_argument("--json", action="store_true", dest="json_output")
    migrate = commands.add_parser(
        "migrate-history",
        description="Replay retained health assessments without collecting data.",
    )
    migrate.add_argument(
        "--dataset",
        required=True,
        choices=["all", *sorted(load_health_manifest().datasets)],
    )
    migrate.add_argument("--network", dest="network_id")
    migrate.add_argument("--policy-config-dir", type=Path, default=None)
    migrate.add_argument("--allow-policy-change", action="store_true")
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--json", action="store_true", dest="json_output")
    migrate.add_argument("--yes", action="store_true")
    migrate.add_argument("--backup-output", type=Path, default=None)
    for name, help_text in (
        ("purge", "Delete health records older than a UTC cutoff"),
        ("purge-all", "Delete all health-domain records"),
        ("purge-by-device", "Delete health records for one device"),
    ):
        purge = commands.add_parser(name, description=help_text)
        purge.add_argument("--dry-run", action="store_true")
        purge.add_argument("--yes", action="store_true")
        purge.add_argument("--json", action="store_true", dest="json_output")
        if name == "purge":
            purge.add_argument("--keep-days", type=int, default=DEFAULT_HEALTH_PURGE_KEEP_DAYS)
        if name == "purge-by-device":
            purge.add_argument("--device", required=True, metavar="EXTADDR")
            purge.add_argument("--network", dest="network_id")
    return parser


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def result_document(result: ProcessingResult) -> dict[str, Any]:
    observation = result.observation
    assessment = result.assessment
    return {
        "schemaVersion": 2,
        "manifestVersion": load_health_manifest().schema_version,
        "datasourceId": observation.datasource_id,
        "datasetId": observation.dataset_id,
        "networkId": observation.network_id,
        "networkName": observation.network_name,
        "observationId": observation.observation_id,
        "assessmentId": assessment.assessment_id,
        "observedAt": observation.observed_at,
        "completeness": observation.completeness.value,
        "status": assessment.status.value,
        "confidence": assessment.confidence.value,
        "policyVersion": assessment.policy_version,
        "policyDigest": assessment.policy_digest,
        "evaluatorVersion": assessment.evaluator_version,
        "profileId": assessment.profile_id,
        "coverage": _jsonable(assessment.coverage),
        "findings": [_jsonable(asdict(finding)) for finding in assessment.findings],
        "observationCreated": result.observation_created,
        "assessmentCreated": result.assessment_created,
    }


def _print_human(document: dict[str, Any], *, dry_run: bool) -> None:
    mode = "dry run" if dry_run else (
        "stored" if document["assessmentCreated"] else "already current"
    )
    print(
        f"{document['status'].title()} ({document['confidence']} confidence), "
        f"{document['completeness']} observation, {mode}"
    )
    print(f"Network: {document['networkName'] or document['networkId']} [{document['networkId']}]")
    print(f"Dataset: {document['datasourceId']} / {document['datasetId']}")
    for finding in document["findings"]:
        if finding["status"] != "strong":
            print(f"- {finding['status'].title()}: {finding['title']} - {finding['summary']}")


def _confirm_purge(args: argparse.Namespace) -> bool:
    if args.dry_run or args.yes:
        return True
    return input("Permanently delete matching health records? [y/N] ").strip().lower() == "y"


def _run_purge(args: argparse.Namespace, data_dir: Path) -> int:
    if not _confirm_purge(args):
        print("Purge cancelled.")
        return 0
    store = SQLiteHealthStore(data_dir / HOBAT_DATABASE_FILENAME)
    if args.health_command == "purge":
        if args.keep_days < 0:
            raise ValueError("--keep-days must be zero or greater")
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.keep_days)
        result = store.purge_before(cutoff, dry_run=args.dry_run)
    elif args.health_command == "purge-all":
        result = store.purge_all(dry_run=args.dry_run)
    else:
        device_id = device_id_from_ext_address(args.device)
        result = store.purge_device(
            device_id, network_id=args.network_id, dry_run=args.dry_run
        )
    document = {
        "command": args.health_command,
        "cutoff": result.cutoff,
        "dryRun": result.dry_run,
        "deleted": dict(result.deleted),
    }
    if args.json_output:
        print(json.dumps(document, sort_keys=True))
    else:
        mode = "Would delete" if result.dry_run else "Deleted"
        print(f"{mode} health records:")
        for table, count in result.deleted.items():
            print(f"- {table}: {count}")
        if result.cutoff:
            print(f"Cutoff (exclusive): {result.cutoff}")
    return 0


def _run_history_migration(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    data_dir: Path,
) -> int:
    if args.dry_run and args.backup_output is not None:
        parser.error("--dry-run cannot be combined with --backup-output")
    if args.backup_output is not None and not args.backup_output.is_absolute():
        parser.error("--backup-output must be an absolute directory path")
    if args.allow_policy_change and args.policy_config_dir is None:
        parser.error("--allow-policy-change requires --policy-config-dir")
    if args.network_id is not None and not re.fullmatch(
        r"extpan:[0-9a-f]{16}", args.network_id
    ):
        parser.error("--network must be a canonical extpan identifier")
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    if not data_dir.is_dir() or not database_path.is_file():
        print(
            f"Health store is not available: {database_path}",
            file=sys.stderr,
        )
        return 4
    dataset_ids = (
        tuple(sorted(load_health_manifest().datasets))
        if args.dataset == "all"
        else (args.dataset,)
    )
    config_dir = args.policy_config_dir or Path.cwd() / "config"
    try:
        policy = load_health_policy(config_dir)
        store = SQLiteHealthStore(database_path, read_only=True)
        inventory = inventory_health_history(
            store,
            target_policy=policy,
            dataset_ids=dataset_ids,
            network_id=args.network_id,
        )
    except (OSError, ValueError, HealthMigrationInventoryError) as exc:
        print(f"Health history preflight failed: {exc}", file=__import__("sys").stderr)
        return 2

    native_digests = {item.policy_digest for item in inventory.items}
    policy_change = any(digest != policy.digest for digest in native_digests)
    if policy_change and (
        not args.allow_policy_change or args.policy_config_dir is None
    ):
        parser.error(
            "Target policy differs from or cannot be verified against native history; "
            "pass --policy-config-dir and --allow-policy-change to acknowledge it"
        )

    report = history_migration_report(
        inventory,
        dry_run=args.dry_run,
        target_policy=policy,
    )
    report["target"]["policyConfigDir"] = str(config_dir.resolve())
    report["target"]["nativePolicyDigests"] = sorted(
        digest for digest in native_digests if digest is not None
    )
    report["target"]["nativePolicyMatches"] = not policy_change
    report["target"]["policyChangeAcknowledged"] = args.allow_policy_change

    actionable = (
        report["totals"]["replayable"]
        + report["totals"]["replayableWithGaps"]
        + report["totals"]["preferencesChanged"]
    )
    if args.dry_run or actionable == 0:
        return_code = (
            1
            if report["totals"]["unsupported"] or report["totals"]["failed"]
            else 0
        )
    else:
        if args.backup_output is None:
            parser.error(
                "--backup-output is required when migration will create revisions "
                "or change preferences"
            )
        if not args.yes:
            if not sys.stdin.isatty():
                parser.error("Noninteractive history migration requires --yes")
            print(
                f"Schema {inventory.schema_version}; {len(inventory.items)} observations; "
                f"{report['totals']['replayableWithGaps']} with context gaps; "
                f"{report['totals']['unsupported']} unsupported. Backup: "
                f"{args.backup_output.resolve()}"
            )
            if input("Commit health-history migration? [y/N] ").strip().lower() != "y":
                report["outcome"] = "cancelled"
                return_code = 0
                if args.json_output:
                    print(json.dumps(report, sort_keys=True))
                else:
                    print("Health-history migration cancelled.")
                return return_code
        writable_store = SQLiteHealthStore(database_path, read_only=True)
        try:
            report = migrate_health_history(
                writable_store,
                data_dir=data_dir,
                target_policy=policy,
                inventory=inventory,
                backup_output=args.backup_output,
            )
        except (OSError, ValueError, HealthMigrationError) as exc:
            print(f"Health-history migration failed: {exc}", file=sys.stderr)
            return 1
        report["target"]["policyConfigDir"] = str(config_dir.resolve())
        report["target"]["nativePolicyDigests"] = sorted(
            digest for digest in native_digests if digest is not None
        )
        report["target"]["nativePolicyMatches"] = not policy_change
        report["target"]["policyChangeAcknowledged"] = args.allow_policy_change
        return_code = (
            1
            if report["totals"]["unsupported"] or report["totals"]["failed"]
            else 0
        )

    if args.json_output:
        print(json.dumps(report, sort_keys=True))
    else:
        print(
            f"Health history {report['outcome']}: "
            f"{report['totals']['observationsScanned']} observations scanned, "
            f"{report['totals']['alreadyCurrent']} already current, "
            f"{report['totals']['replayable']} replayable, "
            f"{report['totals']['replayableWithGaps']} replayable with gaps, "
            f"{report['totals']['unsupported']} unsupported, "
            f"{report['totals']['failed']} failed."
        )
        for item in report["items"]:
            if item["reasons"]:
                print(
                    f"- {item['networkId']} / {item['datasetId']} / "
                    f"{item['observationId']}: {item['eligibility']} "
                    f"({', '.join(item['reasons'])})"
                )
    return return_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = resolve_data_dir(
        args.datadir,
        create_default=args.health_command != "migrate-history",
    )
    if args.health_command == "migrate-history":
        return _run_history_migration(args, parser, data_dir)
    if args.health_command in {"purge", "purge-all", "purge-by-device"}:
        return _run_purge(args, data_dir)
    if args.health_command == "compare":
        database_path = data_dir / HOBAT_DATABASE_FILENAME
        if not database_path.is_file():
            parser.error("Health store is not available")
        store = SQLiteHealthStore(database_path, read_only=args.dry_run)
        try:
            interval, items, created = store.compare_assessments(
                args.before_assessment, args.after_assessment, dry_run=args.dry_run,
            )
        except (KeyError, ValueError) as exc:
            parser.error(str(exc))
        document = {
            "schemaVersion": 1, "comparisonId": interval.comparison_id,
            "beforeAssessmentId": interval.before_assessment_id,
            "afterAssessmentId": interval.after_assessment_id,
            "comparable": interval.compatibility.comparable,
            "reasons": list(interval.compatibility.reasons),
            "itemCount": len(items), "created": created, "dryRun": args.dry_run,
        }
        print(json.dumps(document, sort_keys=True) if args.json_output else (
            f"Comparison {interval.comparison_id}: {len(items)} items, "
            f"{'comparable' if interval.compatibility.comparable else 'not comparable'}"
            f"{' (dry run)' if args.dry_run else ''}"
        ))
        return 0
    policy = load_health_policy(args.policy_config_dir or Path.cwd() / "config")
    if args.dry_run and args.export_latest:
        parser.error("--dry-run cannot be combined with --export-latest")
    roster_actions = sum(
        bool(value)
        for value in (args.init_roster_from_label_map, args.roster_list, args.roster_device)
    )
    if roster_actions > 1:
        parser.error("roster operations are mutually exclusive")
    if (args.roster_label is not None or args.roster_state is not None) and not args.roster_device:
        parser.error("--roster-label and --roster-state require --roster-device")
    if args.dataset == "all" and (roster_actions or args.export_latest):
        parser.error("--dataset all cannot be combined with roster operations or --export-latest")

    if args.init_roster_from_label_map:
        store = SQLiteHealthStore(data_dir / HOBAT_DATABASE_FILENAME)
        imported = import_expected_roster_from_label_map(
            data_dir=data_dir, dataset_id=args.dataset, store=store
        )
        document = {
            "networkId": imported.network_id,
            "imported": imported.imported,
            "alreadyPresent": imported.already_present,
            "skipped": imported.skipped,
        }
        print(json.dumps(document, sort_keys=True) if args.json_output else (
            f"Imported {imported.imported} expected devices for {imported.network_id}; "
            f"already present {imported.already_present}; skipped {imported.skipped}."
        ))
        return 0

    if args.roster_list or args.roster_device:
        store = SQLiteHealthStore(data_dir / HOBAT_DATABASE_FILENAME)
        network_id = network_id_for_dataset(data_dir=data_dir, dataset_id=args.dataset)
        mutation = None
        if args.roster_device:
            try:
                device_id = device_id_from_ext_address(args.roster_device)
            except ValueError as exc:
                parser.error(str(exc))
            try:
                mutation = set_cli_roster_device(
                    store,
                    network_id=network_id,
                    device_id=device_id,
                    label=args.roster_label,
                    state=args.roster_state,
                    label_supplied=args.roster_label is not None,
                )
            except ValueError as exc:
                parser.error(str(exc))
        records = store.expected_device_records(network_id)
        document = {"networkId": network_id, "devices": records}
        if mutation is not None:
            document["mutation"] = asdict(mutation)
        if args.json_output:
            print(json.dumps(document, sort_keys=True))
        else:
            for record in records:
                label = f" ({record['label']})" if record["label"] else ""
                print(f"{record['device_id']} {record['roster_state']}{label}")
        return 0

    dataset_ids = (
        sorted(load_health_manifest().datasets)
        if args.dataset == "all"
        else [args.dataset]
    )
    documents = []
    database_path = data_dir / HOBAT_DATABASE_FILENAME
    store = (
        SQLiteHealthStore(database_path, read_only=True)
        if args.dry_run and database_path.is_file()
        else None
        if args.dry_run
        else SQLiteHealthStore(database_path)
    )
    for dataset_id in dataset_ids:
        kwargs = {
            "data_dir": data_dir,
            "dataset_id": dataset_id,
            "policy": policy,
            "allow_partial": args.allow_partial,
        }
        if args.dry_run:
            result = build_processing_result(**kwargs, store=store)
        else:
            result = process_health(**kwargs, store=store)
        documents.append(result_document(result))
    if args.dataset == "all" and not args.dry_run:
        store.reconcile_current_assessments(tuple(dataset_ids))
    document = documents[0]
    if args.export_latest:
        export_path = Path(args.export_latest)
        if export_path.is_absolute() or export_path.parent != Path("."):
            parser.error("--export-latest must be a leaf filename under --datadir")
        save_json_atomic(document, data_dir / export_path, add_trailing_newline=True)
    if args.json_output:
        print(json.dumps(documents if args.dataset == "all" else document, sort_keys=True))
    else:
        for index, item in enumerate(documents):
            if index:
                print()
            _print_human(item, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())