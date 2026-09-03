"""Command-line interface for cache-only health processing."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from td_health_history import import_expected_roster_from_label_map, network_id_for_dataset
from td_health_manifest import load_health_manifest
from td_health_observation_model import device_id_from_ext_address
from td_health_observation_store import HEALTH_DATABASE_FILENAME
from td_health_policy import load_health_policy
from td_health_processor import ProcessingResult, build_processing_result, process_health
from td_health_sqlite import SQLiteHealthStore
from util_data import resolve_data_dir, save_json_atomic


LATEST_REPORT_FILENAME = "td-health-latest.json"


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
    process_dataset.add_argument("--roster-device", metavar="EXTADDR", help="Upsert this roster device identity.")
    process_dataset.add_argument("--roster-label", help="Label to store with --roster-device.")
    process_dataset.add_argument(
        "--roster-state",
        choices=("expected", "retired", "intentionally-offline", "intermittent"),
        default="expected",
        help="State to store with --roster-device.",
    )
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
        "schemaVersion": 1,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = resolve_data_dir(args.datadir)
    policy = load_health_policy(args.policy_config_dir or Path.cwd() / "config")
    if args.dry_run and args.export_latest:
        parser.error("--dry-run cannot be combined with --export-latest")
    roster_actions = sum(
        bool(value)
        for value in (args.init_roster_from_label_map, args.roster_list, args.roster_device)
    )
    if roster_actions > 1:
        parser.error("roster operations are mutually exclusive")
    if (args.roster_label or args.roster_state != "expected") and not args.roster_device:
        parser.error("--roster-label and --roster-state require --roster-device")
    if args.dataset == "all" and (roster_actions or args.export_latest):
        parser.error("--dataset all cannot be combined with roster operations or --export-latest")

    if args.init_roster_from_label_map:
        store = SQLiteHealthStore(data_dir / HEALTH_DATABASE_FILENAME)
        imported = import_expected_roster_from_label_map(
            data_dir=data_dir, dataset_id=args.dataset, store=store
        )
        document = {
            "networkId": imported.network_id,
            "imported": imported.imported,
            "skipped": imported.skipped,
        }
        print(json.dumps(document, sort_keys=True) if args.json_output else (
            f"Imported {imported.imported} expected devices for {imported.network_id}; "
            f"skipped {imported.skipped}."
        ))
        return 0

    if args.roster_list or args.roster_device:
        store = SQLiteHealthStore(data_dir / HEALTH_DATABASE_FILENAME)
        network_id = network_id_for_dataset(data_dir=data_dir, dataset_id=args.dataset)
        if args.roster_device:
            try:
                device_id = device_id_from_ext_address(args.roster_device)
            except ValueError as exc:
                parser.error(str(exc))
            store.upsert_expected_device(
                network_id,
                device_id,
                args.roster_label,
                args.roster_state,
            )
        records = store.expected_device_records(network_id)
        document = {"networkId": network_id, "devices": records}
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
    store = None if args.dry_run else SQLiteHealthStore(data_dir / HEALTH_DATABASE_FILENAME)
    for dataset_id in dataset_ids:
        kwargs = {
            "data_dir": data_dir,
            "dataset_id": dataset_id,
            "policy": policy,
            "allow_partial": args.allow_partial,
        }
        if args.dry_run:
            result = build_processing_result(**kwargs)
        else:
            result = process_health(**kwargs, store=store)
        documents.append(result_document(result))
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