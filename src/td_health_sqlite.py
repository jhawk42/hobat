"""Atomic SQLite backend for Thread health observations."""

from __future__ import annotations

import json
import hashlib
import math
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Iterator

from td_health_comparison import (
    COMPARISON_INTERVALS, COMPARISON_VERSION, METRIC_CATALOG, ROUTE64_SAMPLE_CONTRACT_VERSION,
    ComparisonItem, ComparisonInterval, ComparisonPolicy, UnsupportedSourceContractError,
    comparison_id, derive_comparison, resolve_interval_candidate, source_roles_for_dataset,
    source_signature,
)
from td_health_manifest import load_health_manifest
from td_health_observation_model import (
    Assessment, Completeness, Confidence, DeviceSample, HealthStatus, MetricSample,
    EvaluationInputDomain, EvaluationInputState, EvaluationInputs, Finding,
    FindingRank, FindingScope, Observation, RelationshipSample, SourceEvidence,
    device_id_from_ext_address,
)
from td_health_observation_store import (
    MAX_OBSERVATIONS,
    HealthStoreFutureSchemaError,
    PurgeResult,
    StoreResult,
)
from td_health_roster import RosterFact


SCHEMA_VERSION = 8
_PURGE_TABLES = (
    "observations",
    "observation_sources",
    "device_samples",
    "relationship_samples",
    "metric_samples",
    "assessments",
    "findings",
    "current_assessments",
    "devices",
    "relationships",
    "expected_devices",
    "network_roster_revisions",
    "roster_lifecycle_events",
    "roster_mutation_receipts",
    "comparisons",
    "comparison_items",
    "health_assessment_preferences",
    "health_assessment_upgrades",
    "health_history_migrations",
    "device_fact_samples",
    "device_last_known",
    "device_identity_conflicts",
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    datasource_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    network_id TEXT NOT NULL,
    network_name TEXT,
    observed_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    completeness TEXT NOT NULL CHECK (completeness IN ('complete','degraded','partial')),
    source_set_digest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_network_time
    ON observations(network_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS observation_sources (
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    digest TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (observation_id, filename)
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    ext_address TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS device_samples (
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    role TEXT,
    state TEXT,
    is_border_router INTEGER NOT NULL,
    source_files_json TEXT NOT NULL,
    PRIMARY KEY (observation_id, device_id)
);
CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    from_device_id TEXT NOT NULL REFERENCES devices(device_id),
    to_device_id TEXT NOT NULL REFERENCES devices(device_id)
);
CREATE TABLE IF NOT EXISTS relationship_samples (
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    relationship_id TEXT NOT NULL REFERENCES relationships(relationship_id),
    relationship_type TEXT NOT NULL,
    link_quality_in INTEGER,
    link_quality_out INTEGER,
    average_rssi REAL,
    last_rssi REAL,
    link_margin REAL,
    frame_error_rate REAL,
    message_error_rate REAL,
    reporter_device_id TEXT REFERENCES devices(device_id),
    source_files_json TEXT NOT NULL,
    PRIMARY KEY (observation_id, relationship_id)
);
CREATE TABLE IF NOT EXISTS metric_samples (
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    denominator REAL,
    source_file TEXT NOT NULL,
    PRIMARY KEY (observation_id, device_id, metric, source_file)
);
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    policy_version TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    evaluator_version TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    roster_context_digest TEXT NOT NULL DEFAULT 'legacy-unknown',
    network_roster_revision INTEGER NOT NULL DEFAULT 0,
    presence_input_digest TEXT NOT NULL DEFAULT 'legacy-unknown',
    reproduction_context_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (observation_id, policy_digest, roster_context_digest)
);
CREATE TABLE IF NOT EXISTS findings (
    assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    rank INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    action TEXT NOT NULL,
    verify TEXT NOT NULL,
    source_files_json TEXT NOT NULL,
    device_ids_json TEXT NOT NULL,
    relationship_ids_json TEXT NOT NULL,
    PRIMARY KEY (assessment_id, finding_id)
);
CREATE TABLE IF NOT EXISTS current_assessments (
    network_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id) ON DELETE CASCADE,
    PRIMARY KEY (network_id, dataset_id)
);
CREATE TABLE IF NOT EXISTS expected_devices (
    network_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    label TEXT,
    roster_state TEXT NOT NULL DEFAULT 'expected',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revision INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    expected_since TEXT,
    change_source TEXT NOT NULL DEFAULT 'legacy',
    PRIMARY KEY (network_id, device_id)
);
CREATE TABLE IF NOT EXISTS network_roster_revisions (
    network_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster_lifecycle_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT,
    network_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    action TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    previous_label TEXT,
    new_label TEXT,
    previous_expected_since TEXT,
    new_expected_since TEXT,
    reason TEXT,
    occurred_at TEXT NOT NULL,
    origin TEXT NOT NULL,
    actor TEXT NOT NULL,
    context_assessment_id TEXT,
    context_observation_id TEXT,
    evidence_basis TEXT,
    device_revision INTEGER NOT NULL,
    network_revision INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roster_lifecycle_network_device
    ON roster_lifecycle_events(network_id, device_id, occurred_at);
CREATE TABLE IF NOT EXISTS roster_mutation_receipts (
    network_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    device_id TEXT,
    request_digest TEXT NOT NULL,
    event_id TEXT,
    result_revision INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    PRIMARY KEY (network_id, request_id)
);
"""

_V4_TABLES = (
    """CREATE TABLE device_fact_samples (
        observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
        device_id TEXT NOT NULL REFERENCES devices(device_id),
        field_key TEXT NOT NULL, source_file TEXT NOT NULL,
        value_json TEXT NOT NULL, value_class TEXT NOT NULL,
        source_observed_at TEXT, roster_policy_digest TEXT, source_rank INTEGER,
        confidence TEXT NOT NULL DEFAULT 'unknown', conflict_state TEXT NOT NULL DEFAULT 'none',
        PRIMARY KEY (observation_id, device_id, field_key, source_file))""",
    """CREATE TABLE device_last_known (
        network_id TEXT NOT NULL, device_id TEXT NOT NULL, field_key TEXT NOT NULL,
        value_json TEXT NOT NULL, value_class TEXT NOT NULL, source_file TEXT,
        observation_id TEXT NOT NULL, source_observed_at TEXT, roster_policy_digest TEXT,
        source_rank INTEGER, confidence TEXT NOT NULL, conflict_state TEXT NOT NULL,
        PRIMARY KEY (network_id, device_id, field_key))""",
    """CREATE TABLE device_identity_conflicts (
        network_id TEXT NOT NULL, device_id TEXT NOT NULL, field_key TEXT NOT NULL,
        value_json TEXT NOT NULL, other_device_id TEXT NOT NULL,
        observation_id TEXT NOT NULL, source_observed_at TEXT,
        roster_policy_digest TEXT, confidence TEXT NOT NULL,
        PRIMARY KEY (network_id, device_id, field_key, value_json))""",
    """CREATE TABLE comparisons (
        comparison_id TEXT PRIMARY KEY, comparison_version TEXT NOT NULL,
        before_assessment_id TEXT NOT NULL, after_assessment_id TEXT NOT NULL,
        before_observation_id TEXT NOT NULL, after_observation_id TEXT NOT NULL,
        before_assessment_digest TEXT NOT NULL, after_assessment_digest TEXT NOT NULL,
        before_observed_at TEXT NOT NULL, after_observed_at TEXT NOT NULL,
        network_id TEXT NOT NULL, datasource_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
        profile_id TEXT NOT NULL, source_signature TEXT,
        sample_contract_version TEXT NOT NULL, evaluator_version TEXT NOT NULL,
        endpoint_policy_digest TEXT, comparison_policy_digest TEXT NOT NULL,
        comparable INTEGER NOT NULL, primary_reason TEXT, reasons_json TEXT NOT NULL,
        elapsed_seconds INTEGER, gap_state TEXT, reset_state TEXT NOT NULL,
        baseline_state TEXT NOT NULL, reset_witness_json TEXT NOT NULL,
        item_count INTEGER NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE INDEX idx_comparisons_page ON comparisons
        (network_id, dataset_id, after_observed_at DESC, comparison_id DESC)""",
    """CREATE TABLE comparison_items (
        comparison_id TEXT NOT NULL REFERENCES comparisons(comparison_id) ON DELETE CASCADE,
        item_id TEXT NOT NULL, scope TEXT NOT NULL, subject_id TEXT NOT NULL,
        item_kind TEXT NOT NULL, metric TEXT, unit TEXT, denominator_kind TEXT,
        before_json TEXT, after_json TEXT, delta_json TEXT,
        direction TEXT, change TEXT NOT NULL, transition_state TEXT,
        sample_count INTEGER NOT NULL, comparable INTEGER NOT NULL,
        primary_reason TEXT, reasons_json TEXT NOT NULL, source_files_json TEXT NOT NULL,
        before_source_time TEXT, after_source_time TEXT,
        reset_state TEXT NOT NULL, reset_witness_json TEXT NOT NULL,
        before_device_id TEXT, after_device_id TEXT,
        before_relationship_id TEXT, after_relationship_id TEXT,
        PRIMARY KEY (comparison_id, item_id))""",
)


class StaleRosterContextError(RuntimeError):
    """Raised when an assessment was evaluated against an obsolete roster revision."""


class ReassessmentBaselineUnavailable(ValueError):
    """Raised when retained evidence cannot reproduce a stored assessment."""


def _context_device_references(context_json: str) -> frozenset[str]:
    try:
        context = json.loads(context_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise sqlite3.DatabaseError(
            "Stored assessment context is invalid during device purge"
        ) from exc
    if not isinstance(context, dict):
        raise sqlite3.DatabaseError(
            "Stored assessment context is invalid during device purge"
        )
    references: set[str] = set()

    def add_id_list(value: object, description: str) -> None:
        if not isinstance(value, list) or not all(
            isinstance(device_id, str) and device_id
            for device_id in value
        ):
            raise sqlite3.DatabaseError(
                f"Stored {description} is invalid during device purge"
            )
        references.update(value)

    def add_absence_map(value: object, description: str) -> None:
        if not isinstance(value, dict) or not all(
            isinstance(device_id, str)
            and device_id
            and type(count) is int
            and count >= 0
            for device_id, count in value.items()
        ):
            raise sqlite3.DatabaseError(
                f"Stored {description} is invalid during device purge"
            )
        references.update(value)

    def add_roster_context(value: object, description: str) -> None:
        if not isinstance(value, dict):
            raise sqlite3.DatabaseError(
                f"Stored {description} is invalid during device purge"
            )
        records = value.get("records", [])
        if not isinstance(records, list):
            raise sqlite3.DatabaseError(
                f"Stored {description} is invalid during device purge"
            )
        for record in records:
            if not isinstance(record, dict):
                raise sqlite3.DatabaseError(
                    f"Stored {description} is invalid during device purge"
                )
            device_id = record.get("deviceId")
            if not isinstance(device_id, str) or not device_id:
                raise sqlite3.DatabaseError(
                    f"Stored {description} is invalid during device purge"
                )
            references.add(device_id)

    def add_address_map(value: object, description: str) -> None:
        if not isinstance(value, dict) or not all(
            isinstance(device_id, str)
            and device_id
            and isinstance(addresses, list)
            and all(isinstance(address, str) for address in addresses)
            for device_id, addresses in value.items()
        ):
            raise sqlite3.DatabaseError(
                f"Stored {description} is invalid during device purge"
            )
        references.update(value)

    for key in ("expectedDeviceIds",):
        if key in context:
            add_id_list(context[key], "expected-device context")
    if "priorCompleteAbsences" in context:
        add_absence_map(
            context["priorCompleteAbsences"], "absence-history context"
        )
    if "rosterContext" in context:
        add_roster_context(context["rosterContext"], "roster context")
    presence = context.get("presenceInputs")
    if presence is not None:
        if not isinstance(presence, dict):
            raise sqlite3.DatabaseError(
                "Stored presence context is invalid during device purge"
            )
        for key in ("observedDeviceIds", "expectedDeviceIds"):
            if key in presence:
                add_id_list(presence[key], "presence-device context")
    evaluation_inputs = context.get("evaluationInputs")
    if evaluation_inputs is not None:
        if not isinstance(evaluation_inputs, dict):
            raise sqlite3.DatabaseError(
                "Stored evaluation inputs are invalid during device purge"
            )
        roster = evaluation_inputs.get("roster")
        if roster is not None:
            if not isinstance(roster, dict):
                raise sqlite3.DatabaseError(
                    "Stored roster inputs are invalid during device purge"
                )
            if "expectedDeviceIds" in roster:
                add_id_list(
                    roster["expectedDeviceIds"], "expected-device context"
                )
            if "context" in roster:
                add_roster_context(roster["context"], "roster context")
        absence = evaluation_inputs.get("absenceHistory")
        if absence is not None:
            if not isinstance(absence, dict):
                raise sqlite3.DatabaseError(
                    "Stored absence inputs are invalid during device purge"
                )
            if "priorCompleteAbsences" in absence:
                add_absence_map(
                    absence["priorCompleteAbsences"],
                    "absence-history context",
                )
        addresses = evaluation_inputs.get("deviceIpv6Addresses")
        if addresses is not None:
            if not isinstance(addresses, dict):
                raise sqlite3.DatabaseError(
                    "Stored address inputs are invalid during device purge"
                )
            for key in ("complete", "observed"):
                if key in addresses:
                    add_address_map(
                        addresses[key], "device-address context"
                    )
        duplicate_ids = evaluation_inputs.get("duplicateRelationshipIds")
        if duplicate_ids is not None:
            add_id_list(duplicate_ids, "duplicate-relationship context")
            for relationship_id in duplicate_ids:
                if not relationship_id.startswith("link:"):
                    raise sqlite3.DatabaseError(
                        "Stored duplicate-relationship identity is invalid during device purge"
                    )
                endpoints = relationship_id.removeprefix("link:").split("->")
                if len(endpoints) != 2 or not all(endpoints):
                    raise sqlite3.DatabaseError(
                        "Stored duplicate-relationship identity is invalid during device purge"
                    )
                references.update(endpoints)
    return frozenset(references)


def _finding_device_references(device_ids_json: str) -> frozenset[str]:
    try:
        device_ids = json.loads(device_ids_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise sqlite3.DatabaseError(
            "Stored finding device identities are invalid during device purge"
        ) from exc
    if not isinstance(device_ids, list) or not all(
        isinstance(device_id, str) and device_id for device_id in device_ids
    ):
        raise sqlite3.DatabaseError(
            "Stored finding device identities are invalid during device purge"
        )
    return frozenset(device_ids)


class SQLiteHealthStore:
    def __init__(
        self,
        path: Path,
        max_observations: int = MAX_OBSERVATIONS,
        *,
        read_only: bool = False,
    ):
        self.path = path
        self.max_observations = max_observations
        self.read_only = read_only
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", timeout=5.0, uri=True
            )
        else:
            connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        if self.read_only:
            connection.execute("PRAGMA query_only=ON")
        else:
            connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _connect_existing_write(self) -> sqlite3.Connection:
        """Open an existing store for a locked migration without initialization."""
        if not self.path.is_file():
            raise FileNotFoundError(f"Health store is not available: {self.path}")
        connection = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=rw", timeout=5.0, uri=True
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if table:
                row = connection.execute(
                    "SELECT MAX(version) AS version FROM schema_migrations"
                ).fetchone()
                version = row["version"] if row else None
                if version is not None and version > SCHEMA_VERSION:
                    raise HealthStoreFutureSchemaError(
                        f"Database schema {version} is newer than supported {SCHEMA_VERSION}"
                    )
                if version is not None and version < 6:
                    connection.execute("PRAGMA foreign_keys=OFF")
            connection.executescript(_SCHEMA)
            applied_versions = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if 2 not in applied_versions:
                connection.execute(
                    "UPDATE assessments SET status=CASE status "
                    "WHEN 'healthy' THEN 'strong' WHEN 'unstable' THEN 'moderate' "
                    "WHEN 'unhealthy' THEN 'poor' ELSE status END"
                )
                connection.execute(
                    "UPDATE findings SET status=CASE status "
                    "WHEN 'healthy' THEN 'strong' WHEN 'unstable' THEN 'moderate' "
                    "WHEN 'unhealthy' THEN 'poor' ELSE status END"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (2,),
                )
            if 3 not in applied_versions:
                assessment_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(assessments)")
                }
                if "evaluator_version" not in assessment_columns:
                    connection.execute(
                        "ALTER TABLE assessments ADD COLUMN evaluator_version "
                        "TEXT NOT NULL DEFAULT 'legacy-unknown'"
                    )
                if "profile_id" not in assessment_columns:
                    connection.execute(
                        "ALTER TABLE assessments ADD COLUMN profile_id "
                        "TEXT NOT NULL DEFAULT 'legacy-unknown'"
                    )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (3,),
                )
            if 4 not in applied_versions:
                for table, column, definition in (
                    ("assessments", "sample_contract_version", "TEXT NOT NULL DEFAULT 'legacy-unknown'"),
                    ("assessments", "health_policy_digest", "TEXT"),
                    ("metric_samples", "metric_kind", "TEXT NOT NULL DEFAULT 'legacy-unknown'"),
                    ("metric_samples", "denominator_kind", "TEXT NOT NULL DEFAULT 'legacy-unknown'"),
                    ("observation_sources", "source_observed_at", "TEXT"),
                    ("relationship_samples", "queued_message_count", "REAL"),
                ):
                    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                    if column not in columns:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                for statement in _V4_TABLES:
                    connection.execute(statement)
                for item in connection.execute(
                    """SELECT ds.observation_id, ds.device_id, ds.role, ds.state
                       FROM device_samples ds ORDER BY ds.observation_id, ds.device_id"""
                ):
                    for field, value, value_class in (
                        ("extAddress", item["device_id"].removeprefix("extaddr:"), "identity"),
                        ("role", item["role"], "transient"),
                        ("state", item["state"], "transient"),
                    ):
                        if value is not None:
                            connection.execute(
                                """INSERT INTO device_fact_samples
                                   (observation_id, device_id, field_key, source_file,
                                    value_json, value_class) VALUES (?, ?, ?, ?, ?, ?)""",
                                (item["observation_id"], item["device_id"], field,
                                 "legacy-unknown", json.dumps(value), value_class),
                            )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (4,),
                )
            if 5 not in applied_versions:
                expected_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(expected_devices)")
                }
                for column, definition in (
                    ("revision", "INTEGER NOT NULL DEFAULT 0"),
                    ("reason", "TEXT"),
                    ("expected_since", "TEXT"),
                    ("change_source", "TEXT NOT NULL DEFAULT 'legacy'"),
                ):
                    if column not in expected_columns:
                        connection.execute(
                            f"ALTER TABLE expected_devices ADD COLUMN {column} {definition}"
                        )
                connection.execute(
                    """INSERT OR IGNORE INTO network_roster_revisions
                       (network_id, revision, updated_at)
                       SELECT DISTINCT network_id, 0, CURRENT_TIMESTAMP
                       FROM expected_devices"""
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (5,),
                )
            if 6 not in applied_versions:
                indexes = connection.execute("PRAGMA index_list(assessments)").fetchall()
                legacy_unique = False
                for index in indexes:
                    if not index["unique"]:
                        continue
                    columns = [
                        row["name"] for row in connection.execute(
                            f"PRAGMA index_info('{index['name']}')"
                        )
                    ]
                    if columns == ["observation_id", "policy_digest"]:
                        legacy_unique = True
                        break
                if legacy_unique:
                    connection.execute(
                        """CREATE TABLE assessments_v6 (
                            assessment_id TEXT PRIMARY KEY,
                            observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
                            policy_version TEXT NOT NULL,
                            policy_digest TEXT NOT NULL,
                            evaluator_version TEXT NOT NULL,
                            profile_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            confidence TEXT NOT NULL,
                            coverage_json TEXT NOT NULL,
                            assessed_at TEXT NOT NULL,
                            sample_contract_version TEXT NOT NULL DEFAULT 'legacy-unknown',
                            health_policy_digest TEXT,
                            roster_context_digest TEXT NOT NULL DEFAULT 'legacy-unknown',
                            network_roster_revision INTEGER NOT NULL DEFAULT 0,
                            presence_input_digest TEXT NOT NULL DEFAULT 'legacy-unknown',
                            reproduction_context_json TEXT NOT NULL DEFAULT '{}',
                            UNIQUE(observation_id, policy_digest, roster_context_digest)
                        )"""
                    )
                    connection.execute(
                        """INSERT INTO assessments_v6
                           (assessment_id, observation_id, policy_version, policy_digest,
                            evaluator_version, profile_id, status, confidence, coverage_json,
                            assessed_at, sample_contract_version, health_policy_digest,
                            roster_context_digest, network_roster_revision,
                            presence_input_digest, reproduction_context_json)
                           SELECT assessment_id, observation_id, policy_version, policy_digest,
                                  evaluator_version, profile_id, status, confidence, coverage_json,
                                  assessed_at, sample_contract_version, health_policy_digest,
                                  'legacy-unknown', 0, 'legacy-unknown', '{}'
                           FROM assessments"""
                    )
                    connection.execute("DROP TABLE assessments")
                    connection.execute("ALTER TABLE assessments_v6 RENAME TO assessments")
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (6,),
                )
            if 7 not in applied_versions:
                receipt_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(roster_mutation_receipts)")
                }
                if "device_id" not in receipt_columns:
                    connection.execute(
                        "ALTER TABLE roster_mutation_receipts ADD COLUMN device_id TEXT"
                    )
                for receipt in connection.execute(
                    """SELECT network_id, request_id, response_json
                       FROM roster_mutation_receipts WHERE device_id IS NULL"""
                ).fetchall():
                    try:
                        response = json.loads(receipt["response_json"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    device_id = response.get("deviceId") if isinstance(response, dict) else None
                    if isinstance(device_id, str):
                        connection.execute(
                            """UPDATE roster_mutation_receipts SET device_id=?
                               WHERE network_id=? AND request_id=?""",
                            (device_id, receipt["network_id"], receipt["request_id"]),
                        )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_roster_receipts_network_device "
                    "ON roster_mutation_receipts(network_id, device_id)"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                    (7,),
                )
                connection.commit()
                foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                if foreign_key_errors:
                    raise sqlite3.DatabaseError("Health schema migration left invalid foreign keys")
                connection.execute("PRAGMA foreign_keys=ON")
            if 8 not in applied_versions:
                self._ensure_schema_v8(connection)
            self._repair_current_assessments(connection)

    @staticmethod
    def _ensure_schema_v8(connection: sqlite3.Connection) -> None:
        """Create preference/lineage tables and backfill legacy selections."""
        for statement in (
            """CREATE TABLE IF NOT EXISTS health_history_migrations (
                migration_id TEXT PRIMARY KEY,
                network_id TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                target_contract_digest TEXT NOT NULL,
                source_inventory_digest TEXT NOT NULL,
                input_schema_version INTEGER NOT NULL,
                output_schema_version INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                committed_at TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                backup_manifest_digest TEXT NOT NULL,
                counts_json TEXT NOT NULL,
                reasons_json TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS health_assessment_upgrades (
                source_assessment_id TEXT NOT NULL
                    REFERENCES assessments(assessment_id) ON DELETE CASCADE,
                target_contract_digest TEXT NOT NULL,
                target_assessment_id TEXT NOT NULL
                    REFERENCES assessments(assessment_id) ON DELETE CASCADE,
                migration_id TEXT NOT NULL
                    REFERENCES health_history_migrations(migration_id) ON DELETE RESTRICT,
                replay_input_digest TEXT NOT NULL,
                unavailable_domains_json TEXT NOT NULL,
                PRIMARY KEY (source_assessment_id, target_contract_digest),
                UNIQUE (target_assessment_id)
            )""",
            """CREATE TABLE IF NOT EXISTS health_assessment_preferences (
                observation_id TEXT PRIMARY KEY
                    REFERENCES observations(observation_id) ON DELETE CASCADE,
                assessment_id TEXT NOT NULL
                    REFERENCES assessments(assessment_id) ON DELETE CASCADE,
                selection_basis_assessment_id TEXT NOT NULL
                    REFERENCES assessments(assessment_id) ON DELETE CASCADE,
                origin TEXT NOT NULL CHECK (origin IN ('native', 'migration')),
                migration_id TEXT
                    REFERENCES health_history_migrations(migration_id) ON DELETE RESTRICT,
                CHECK ((origin = 'native' AND migration_id IS NULL)
                    OR (origin = 'migration' AND migration_id IS NOT NULL))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_health_upgrades_target "
            "ON health_assessment_upgrades(target_assessment_id)",
            "CREATE INDEX IF NOT EXISTS idx_health_upgrades_migration "
            "ON health_assessment_upgrades(migration_id)",
            "CREATE INDEX IF NOT EXISTS idx_health_preferences_assessment "
            "ON health_assessment_preferences(assessment_id)",
            "CREATE INDEX IF NOT EXISTS idx_health_preferences_basis "
            "ON health_assessment_preferences(selection_basis_assessment_id)",
        ):
            connection.execute(statement)

        observations = connection.execute(
            """SELECT o.observation_id, a.assessment_id, a.assessed_at,
                      a.network_roster_revision
               FROM observations o JOIN assessments a USING (observation_id)
               ORDER BY o.observation_id"""
        ).fetchall()
        by_observation: dict[str, list[sqlite3.Row]] = {}
        for row in observations:
            by_observation.setdefault(row["observation_id"], []).append(row)
        for observation_id, candidates in by_observation.items():
            selected = max(
                candidates,
                key=lambda row: (
                    int(row["network_roster_revision"]),
                    SQLiteHealthStore._utc_instant(row["assessed_at"]),
                    row["assessment_id"],
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO health_assessment_preferences
                   (observation_id, assessment_id, selection_basis_assessment_id,
                    origin, migration_id)
                   VALUES (?, ?, ?, 'native', NULL)""",
                (
                    observation_id,
                    selected["assessment_id"],
                    selected["assessment_id"],
                ),
            )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (8, CURRENT_TIMESTAMP)"
        )

    def save_processing_result(
        self, observation: Observation, assessment: Assessment,
        *, roster_facts: tuple[RosterFact, ...] = (),
    ) -> StoreResult:
        if assessment.observation_id != observation.observation_id:
            raise ValueError("Assessment and observation IDs do not match")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if assessment.roster_context_digest != "legacy-unknown":
                current_revision = connection.execute(
                    "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                    (observation.network_id,),
                ).fetchone()
                current_revision_value = int(current_revision["revision"]) if current_revision else 0
                if current_revision_value != assessment.network_roster_revision:
                    raise StaleRosterContextError(
                        "Roster changed during health processing; retry with the current roster."
                    )
            observation_created = self._insert_observation(connection, observation)
            had_assessment_before = connection.execute(
                "SELECT 1 FROM assessments WHERE observation_id=? LIMIT 1",
                (observation.observation_id,),
            ).fetchone() is not None
            if not observation_created and assessment.sample_contract_version == ROUTE64_SAMPLE_CONTRACT_VERSION:
                versions = {row[0] for row in connection.execute(
                    "SELECT DISTINCT sample_contract_version FROM assessments WHERE observation_id=?",
                    (observation.observation_id,),
                )}
                if versions and versions != {ROUTE64_SAMPLE_CONTRACT_VERSION}:
                    raise ValueError("Cannot upgrade immutable observation samples to a new sample contract")
            if observation_created and roster_facts:
                self._insert_roster_facts(connection, observation, roster_facts)
            assessment_created = self._insert_assessment(connection, assessment)
            self.consider_native_preference(
                connection,
                assessment.assessment_id,
                new_observation=observation_created or not had_assessment_before,
            )
            self._auto_compare(connection, observation, assessment)
            self._set_current_assessment(
                connection, observation.network_id, observation.dataset_id
            )
            self._prune_observations(connection)
            connection.commit()
            return StoreResult(observation_created, assessment_created)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _insert_roster_facts(connection: sqlite3.Connection, observation: Observation,
                             facts: tuple[RosterFact, ...]) -> None:
        policy = load_health_manifest().roster_policy
        source_times = {source.filename: source.source_observed_at
                        for source in observation.sources if source.kind == "final" and source.state == "valid"}
        grouped: dict[tuple[str, str, str], set[str]] = {}
        observed_devices = {device.device_id for device in observation.devices}
        for fact in facts:
            if fact.device_id not in observed_devices:
                continue
            if policy.sources.get(fact.field_key, {}).get(fact.source_file) != fact.source_rank:
                continue
            grouped.setdefault((fact.device_id, fact.field_key, fact.source_file), set()).add(fact.value_json)
        candidates: dict[tuple[str, str], list[tuple[RosterFact, str, str]]] = {}
        disagreements: set[tuple[str, str]] = set()
        by_key = {(fact.device_id, fact.field_key, fact.source_file): fact for fact in facts}
        for (device_id, field, filename), values in sorted(grouped.items()):
            fact = by_key[device_id, field, filename]
            conflict = "same-source" if len(values) > 1 else "none"
            value_json = (json.dumps([json.loads(value) for value in sorted(values)],
                                     sort_keys=True, separators=(",", ":"))
                          if conflict != "none" else next(iter(values)))
            source_time = source_times.get(filename)
            connection.execute(
                """INSERT INTO device_fact_samples
                   (observation_id, device_id, field_key, source_file, value_json,
                    value_class, source_observed_at, roster_policy_digest, source_rank,
                    confidence, conflict_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (observation.observation_id, device_id, field, filename, value_json,
                 fact.value_class, source_time, policy.digest, fact.source_rank,
                 fact.confidence, conflict),
            )
            if conflict != "none":
                disagreements.add((device_id, field))
            if source_time and conflict == "none":
                candidates.setdefault((device_id, field), []).append((fact, value_json, source_time))
        for key, options in candidates.items():
            if len({item[1] for item in options}) > 1:
                disagreements.add(key)
        for device_id, field in sorted(disagreements):
            connection.execute(
                """UPDATE device_fact_samples SET conflict_state='cross-source'
                   WHERE observation_id=? AND device_id=? AND field_key=?
                   AND conflict_state='none'""",
                (observation.observation_id, device_id, field),
            )
        if observation.completeness is not Completeness.COMPLETE:
            return
        for (device_id, field), options in sorted(candidates.items()):
            if (device_id, field) in disagreements:
                continue
            highest = max(item[0].source_rank for item in options)
            top = [item for item in options if item[0].source_rank == highest]
            fact, value_json, source_time = max(top, key=lambda item: (item[2], item[0].source_file))
            current = connection.execute(
                """SELECT * FROM device_last_known WHERE network_id=? AND device_id=? AND field_key=?""",
                (observation.network_id, device_id, field),
            ).fetchone()
            if current:
                if current["roster_policy_digest"] not in (None, policy.digest) or (current["source_rank"] or 0) > highest:
                    continue
                if current["source_observed_at"]:
                    newer = datetime.fromisoformat(source_time) > datetime.fromisoformat(current["source_observed_at"])
                    if not newer and (fact.source_file == current["source_file"] or
                                      datetime.fromisoformat(source_time) < datetime.fromisoformat(current["source_observed_at"])):
                        continue
                    if not newer and (observation.observation_id, fact.source_file) <= (current["observation_id"], current["source_file"]):
                        continue
            connection.execute(
                """INSERT INTO device_last_known
                   (network_id, device_id, field_key, value_json, value_class, source_file,
                    observation_id, source_observed_at, roster_policy_digest, source_rank,
                    confidence, conflict_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none')
                   ON CONFLICT(network_id, device_id, field_key) DO UPDATE SET
                   value_json=excluded.value_json, value_class=excluded.value_class,
                   source_file=excluded.source_file, observation_id=excluded.observation_id,
                   source_observed_at=excluded.source_observed_at,
                   roster_policy_digest=excluded.roster_policy_digest,
                   source_rank=excluded.source_rank, confidence=excluded.confidence,
                   conflict_state=excluded.conflict_state""",
                (observation.network_id, device_id, field, value_json, fact.value_class,
                 fact.source_file, observation.observation_id, source_time, policy.digest,
                 fact.source_rank, fact.confidence),
            )
        SQLiteHealthStore._refresh_alias_conflicts(connection, observation.network_id)

    @staticmethod
    def _refresh_alias_conflicts(connection: sqlite3.Connection, network_id: str) -> None:
        policy = load_health_manifest().roster_policy
        connection.execute("DELETE FROM device_identity_conflicts WHERE network_id=?", (network_id,))
        rows = connection.execute(
            """SELECT * FROM device_last_known WHERE network_id=?
               AND field_key IN ('eui', 'eui64', 'rloc16', 'routerId')
               AND roster_policy_digest=? AND source_observed_at IS NOT NULL
               ORDER BY field_key, value_json, device_id""",
            (network_id, policy.digest),
        ).fetchall()
        now = datetime.now(timezone.utc)
        for index, first in enumerate(rows):
            age = (now - datetime.fromisoformat(first["source_observed_at"])).total_seconds()
            expiry = policy.freshness_seconds[first["field_key"]]
            if age < 0 or (expiry is not None and age > expiry) or age > policy.alias_collision_window_seconds:
                continue
            for second in rows[index + 1:]:
                if (first["field_key"], first["value_json"]) != (second["field_key"], second["value_json"]):
                    continue
                if first["device_id"] == second["device_id"]:
                    continue
                second_age = (now - datetime.fromisoformat(second["source_observed_at"])).total_seconds()
                if second_age < 0 or (expiry is not None and second_age > expiry):
                    continue
                if abs((datetime.fromisoformat(first["source_observed_at"]) -
                        datetime.fromisoformat(second["source_observed_at"])).total_seconds()) > policy.alias_collision_window_seconds:
                    continue
                for row, other in ((first, second), (second, first)):
                    connection.execute(
                        """INSERT OR IGNORE INTO device_identity_conflicts
                           (network_id, device_id, field_key, value_json, other_device_id,
                            observation_id, source_observed_at, roster_policy_digest, confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (network_id, row["device_id"], row["field_key"], row["value_json"],
                         other["device_id"], row["observation_id"], row["source_observed_at"],
                         row["roster_policy_digest"], row["confidence"]),
                    )

    @staticmethod
    def _endpoint(connection: sqlite3.Connection, assessment_id: str) -> tuple[Observation, Assessment] | None:
        row = connection.execute(
            """SELECT a.*, o.* FROM assessments a JOIN observations o USING (observation_id)
               WHERE a.assessment_id=?""", (assessment_id,)
        ).fetchone()
        if row is None:
            return None
        observation_id = row["observation_id"]
        sources = tuple(SourceEvidence(item["filename"], item["digest"], item["kind"],
                                       item["state"], item["source_observed_at"])
                        for item in connection.execute(
                            "SELECT * FROM observation_sources WHERE observation_id=? ORDER BY filename", (observation_id,)))
        devices = tuple(DeviceSample(item["device_id"], item["device_id"].removeprefix("extaddr:"),
                                     item["role"], item["state"], bool(item["is_border_router"]),
                                     tuple(json.loads(item["source_files_json"])))
                        for item in connection.execute(
                            "SELECT * FROM device_samples WHERE observation_id=? ORDER BY device_id", (observation_id,)))
        relationships = tuple(RelationshipSample(
            item["relationship_id"], item["relationship_type"], item["from_device_id"],
            item["to_device_id"], item["link_quality_in"], item["link_quality_out"],
            item["average_rssi"], item["last_rssi"], item["link_margin"],
            item["frame_error_rate"], item["message_error_rate"], item["reporter_device_id"],
            tuple(json.loads(item["source_files_json"])), item["queued_message_count"])
            for item in connection.execute(
                """SELECT rs.*, r.from_device_id, r.to_device_id FROM relationship_samples rs
                   JOIN relationships r USING (relationship_id)
                   WHERE rs.observation_id=? ORDER BY rs.relationship_id""", (observation_id,)))
        metrics = tuple(MetricSample(item["device_id"], item["metric"], item["value"],
                                     item["unit"], item["denominator"], item["source_file"])
                        for item in connection.execute(
                            "SELECT * FROM metric_samples WHERE observation_id=? ORDER BY device_id, metric, source_file", (observation_id,)))
        observation = Observation(observation_id, row["datasource_id"], row["dataset_id"],
                                  row["network_id"], row["network_name"], row["observed_at"],
                                  row["ingested_at"], Completeness(row["completeness"]),
                                  row["source_set_digest"], sources, devices, relationships, metrics)
        assessment = Assessment(row["assessment_id"], observation_id, row["policy_version"],
                                row["policy_digest"], row["evaluator_version"], row["profile_id"],
                                HealthStatus(row["status"]), Confidence(row["confidence"]), {}, (),
                                row["assessed_at"], row["sample_contract_version"], row["health_policy_digest"])
        return observation, assessment

    @staticmethod
    def _store_comparison(connection: sqlite3.Connection, before: tuple[Observation, Assessment],
                          after: tuple[Observation, Assessment], interval: ComparisonInterval,
                          items: tuple[ComparisonItem, ...], *,
                          enforce_retention: bool = True) -> str:
        old_obs, old_assessment = before
        new_obs, new_assessment = after
        reset_states = {item.reset_evidence.state for item in items if item.reset_evidence}
        reset_summary = "reset-detected" if "reset-detected" in reset_states else "unknown" if "unknown" in reset_states else "same-epoch" if "same-epoch" in reset_states else "not-applicable"
        witness = {item.item_id: {"witness": item.reset_evidence.witness,
                      "before": item.reset_evidence.before_value,
                      "after": item.reset_evidence.after_value}
               for item in items if item.reset_evidence}
        connection.execute(
            """INSERT INTO comparisons VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (interval.comparison_id, COMPARISON_VERSION, old_assessment.assessment_id,
             new_assessment.assessment_id, old_obs.observation_id, new_obs.observation_id,
             old_assessment.policy_digest, new_assessment.policy_digest,
             old_obs.observed_at, new_obs.observed_at, new_obs.network_id,
             new_obs.datasource_id, new_obs.dataset_id, new_assessment.profile_id,
             interval.source_signature, new_assessment.sample_contract_version,
             new_assessment.evaluator_version, interval.endpoint_policy_digest,
             interval.comparison_policy_digest, int(interval.compatibility.comparable),
             interval.compatibility.primary_reason, json.dumps(interval.compatibility.reasons),
             interval.elapsed_seconds, interval.gap_state, reset_summary, interval.baseline_state,
             json.dumps(witness, sort_keys=True), len(items), datetime.now(timezone.utc).isoformat()),
        )
        for item in items:
            has_before = item.before_value is not None and (
                item.kind not in {"presence-transition", "relationship-change"} or item.before_value is True
            )
            has_after = item.after_value is not None and (
                item.kind not in {"presence-transition", "relationship-change"} or item.after_value is True
            )
            connection.execute(
                """INSERT INTO comparison_items VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (interval.comparison_id, item.item_id, item.scope, item.subject_id,
                 item.kind, item.metric, item.unit, item.denominator_kind,
                 json.dumps(item.before_value, allow_nan=False), json.dumps(item.after_value, allow_nan=False),
                 json.dumps(item.delta, allow_nan=False), item.direction, item.change, item.transition,
                 item.sample_count, int(item.compatibility.comparable), item.compatibility.primary_reason,
                 json.dumps(item.compatibility.reasons), json.dumps(item.source_files),
                 item.before_source_time, item.after_source_time,
                 item.reset_evidence.state if item.reset_evidence else "not-applicable",
                 json.dumps({"witness": item.reset_evidence.witness,
                             "before": item.reset_evidence.before_value,
                             "after": item.reset_evidence.after_value} if item.reset_evidence else {}),
                 item.subject_id if item.scope == "device" and has_before else None,
                 item.subject_id if item.scope == "device" and has_after else None,
                 item.subject_id if item.scope == "relationship" and has_before else None,
                 item.subject_id if item.scope == "relationship" and has_after else None),
            )
        if enforce_retention:
            connection.execute(
                """DELETE FROM comparisons WHERE comparison_id IN (
                   SELECT comparison_id FROM comparisons ORDER BY after_observed_at DESC,
                   comparison_id DESC LIMIT -1 OFFSET 2000)"""
            )
        return interval.comparison_id

    @staticmethod
    def _derive_pair(connection: sqlite3.Connection,
                     before: tuple[Observation, Assessment], after: tuple[Observation, Assessment]
                     ) -> tuple[ComparisonInterval, tuple[ComparisonItem, ...]]:
        dataset = load_health_manifest().dataset(after[0].dataset_id)
        endpoint_facts = {}
        for observation in (before[0], after[0]):
            rows = connection.execute(
                """SELECT device_id, field_key, source_file, source_observed_at,
                          roster_policy_digest, conflict_state, value_json
                   FROM device_fact_samples WHERE observation_id=?
                   AND field_key IN ('leaderData.partitionId', 'rloc16')""",
                (observation.observation_id,),
            ).fetchall()
            endpoint_facts[observation.observation_id] = tuple(
                {**dict(row), "value": json.loads(row["value_json"])} for row in rows
            )
        return derive_comparison(before, after, source_roles=source_roles_for_dataset(dataset),
                                 endpoint_facts=endpoint_facts)

    def compare_assessments(self, before_assessment_id: str, after_assessment_id: str,
                            *, dry_run: bool = False) -> tuple[ComparisonInterval, tuple[ComparisonItem, ...], bool]:
        connection = self._connect()
        try:
            connection.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
            before = self._endpoint(connection, before_assessment_id)
            after = self._endpoint(connection, after_assessment_id)
            if before is None or after is None:
                raise KeyError("Assessment endpoint not found")
            interval, items = self._derive_pair(connection, before, after)
            if "endpoint-order-invalid" in interval.compatibility.reasons:
                raise ValueError("Before assessment must precede after assessment")
            inserted = False
            if not dry_run:
                present = connection.execute("SELECT 1 FROM comparisons WHERE comparison_id=?",
                                             (interval.comparison_id,)).fetchone()
                if not present:
                    self._store_comparison(connection, before, after, interval, items)
                    inserted = True
            if dry_run:
                connection.rollback()
            else:
                connection.commit()
            return interval, items, inserted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def comparison_rows(self, *, network_id: str, dataset_id: str,
                        limit: int, offset: int) -> tuple[list[dict], int]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            total = connection.execute(
                "SELECT COUNT(*) FROM comparisons WHERE network_id=? AND dataset_id=?",
                (network_id, dataset_id),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT c.*, EXISTS(SELECT 1 FROM observations o
                   WHERE o.observation_id=c.before_observation_id) AS before_retained,
                   EXISTS(SELECT 1 FROM observations o
                   WHERE o.observation_id=c.after_observation_id) AS after_retained
                   FROM comparisons c WHERE network_id=? AND dataset_id=?
                   ORDER BY after_observed_at DESC, comparison_id DESC LIMIT ? OFFSET ?""",
                (network_id, dataset_id, limit, offset),
            ).fetchall()
            result = []
            for value in rows:
                row = dict(value)
                for side in ("before", "after"):
                    assessment_id = row[f"{side}_assessment_id"]
                    observation_id = row[f"{side}_observation_id"]
                    row[f"{side}_context_metadata"] = (
                        self.assessment_context_metadata(
                            connection, assessment_id
                        )
                        if row[f"{side}_retained"]
                        else None
                    )
                    schema_version = int(
                        connection.execute(
                            "SELECT MAX(version) FROM schema_migrations"
                        ).fetchone()[0]
                        or 0
                    )
                    if not row[f"{side}_retained"]:
                        revision_state = "pruned"
                    elif schema_version < 8:
                        revision_state = "preferred"
                    else:
                        preference = self.preferred_assessment_for_observation_on_connection(
                            connection, observation_id
                        )
                        revision_state = (
                            "preferred"
                            if preference["assessment_id"] == assessment_id
                            else "superseded"
                        )
                    row[f"{side}_revision_state"] = revision_state
                result.append(row)
            return result, total

    @staticmethod
    def assessment_context_metadata(
        connection: sqlite3.Connection, assessment_id: str
    ) -> dict:
        schema_version = int(
            connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            or 0
        )
        assessment_columns = {
            item["name"]
            for item in connection.execute("PRAGMA table_info(assessments)")
        }
        roster_revision = (
            "a.network_roster_revision"
            if "network_roster_revision" in assessment_columns
            else "0 AS network_roster_revision"
        )
        if schema_version >= 8:
            row = connection.execute(
                f"""SELECT a.coverage_json, a.reproduction_context_json,
                          a.evaluator_version, {roster_revision},
                          u.source_assessment_id, m.committed_at
                   FROM assessments a
                   LEFT JOIN health_assessment_upgrades u
                     ON u.target_assessment_id=a.assessment_id
                   LEFT JOIN health_history_migrations m USING (migration_id)
                   WHERE a.assessment_id=?""",
                (assessment_id,),
            ).fetchone()
        else:
            row = connection.execute(
                f"""SELECT coverage_json, reproduction_context_json,
                          evaluator_version,
                          {"network_roster_revision" if "network_roster_revision" in assessment_columns else "0 AS network_roster_revision"},
                          NULL AS source_assessment_id, NULL AS committed_at
                   FROM assessments WHERE assessment_id=?""",
                (assessment_id,),
            ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Assessment context metadata is missing")
        try:
            coverage = json.loads(row["coverage_json"])
            context = json.loads(row["reproduction_context_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise sqlite3.DatabaseError(
                "Stored assessment context metadata is invalid"
            ) from exc
        if not isinstance(coverage, dict) or not isinstance(context, dict):
            raise sqlite3.DatabaseError("Stored assessment context metadata is invalid")
        inputs = context.get("evaluationInputs")
        domains = inputs.get("domains") if isinstance(inputs, dict) else None
        roster_domain = domains.get("roster") if isinstance(domains, dict) else None
        historical_revision = (
            context.get("networkRosterRevision")
            if isinstance(roster_domain, dict)
            and roster_domain.get("state") == "available"
            else None
        )
        return {
            "evaluationContextComplete": coverage.get(
                "evaluationContextComplete"
            ),
            "verdictContextComplete": coverage.get(
                "verdictContextComplete"
            ),
            "unavailableEvaluationDomains": coverage.get(
                "unavailableEvaluationDomains"
            ),
            "networkRosterRevision": row["network_roster_revision"],
            "historicalRosterRevision": historical_revision,
            "migration": (
                {
                    "sourceAssessmentId": row["source_assessment_id"],
                    "targetEvaluatorVersion": row["evaluator_version"],
                    "committedAt": row["committed_at"],
                }
                if row["source_assessment_id"] is not None
                else None
            ),
        }

    @staticmethod
    def _utc_instant(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise sqlite3.DatabaseError("Invalid stored health timestamp") from exc
        if parsed.utcoffset() is None:
            raise sqlite3.DatabaseError("Stored health timestamp has no timezone")
        return parsed.astimezone(timezone.utc)

    def assessment_endpoint_page(
        self, *, network_id: str, dataset_id: str, side: str, limit: int, offset: int,
        after_assessment_id: str | None = None, selected_assessment_id: str | None = None,
    ) -> dict:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            assessment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(assessments)")
            }
            roster_revision = (
                "a.network_roster_revision" if "network_roster_revision" in assessment_columns
                else "0 AS network_roster_revision"
            )
            records = [
                dict(row) for row in connection.execute(
                    f"""SELECT a.assessment_id, a.assessed_at,
                              {roster_revision}, o.observation_id,
                              o.network_id, o.network_name, o.datasource_id, o.dataset_id,
                              o.observed_at, o.completeness
                       FROM assessments a JOIN observations o USING (observation_id)
                       WHERE o.network_id=? AND o.dataset_id=?""",
                    (network_id, dataset_id),
                )
            ]
            instants = {
                row["assessment_id"]: (
                    self._utc_instant(row["observed_at"]),
                    self._utc_instant(row["assessed_at"]),
                )
                for row in records
            }
            records.sort(
                key=lambda row: (
                    instants[row["assessment_id"]][0],
                    row["network_roster_revision"],
                    instants[row["assessment_id"]][1],
                    row["assessment_id"],
                ),
                reverse=True,
            )
            by_id = {row["assessment_id"]: row for row in records}
            candidate_records = self.preferred_assessments_on_connection(
                connection, records
            )
            if selected_assessment_id and selected_assessment_id not in by_id:
                raise KeyError("Selected assessment endpoint not found")
            if side == "before":
                if not after_assessment_id or after_assessment_id not in by_id:
                    raise KeyError("After assessment endpoint not found")
                after_instant = instants[after_assessment_id][0]
                candidates = [
                    row for row in candidate_records
                    if instants[row["assessment_id"]][0] < after_instant
                ]
                if selected_assessment_id and selected_assessment_id not in {
                    row["assessment_id"] for row in candidates
                }:
                    selected = by_id[selected_assessment_id]
                    if (
                        instants[selected_assessment_id][0] < after_instant
                        or selected["observation_id"] == by_id[after_assessment_id]["observation_id"]
                    ):
                        candidates.append(selected)
                    else:
                        raise ValueError("Selected Before assessment must precede After")
            else:
                if after_assessment_id is not None:
                    raise ValueError("after assessment is only valid for the before side")
                candidates = list(candidate_records)
                if selected_assessment_id and selected_assessment_id not in {
                    row["assessment_id"] for row in candidates
                }:
                    candidates.append(by_id[selected_assessment_id])
            candidates.sort(
                key=lambda row: (
                    instants[row["assessment_id"]][0],
                    row["network_roster_revision"],
                    instants[row["assessment_id"]][1],
                    row["assessment_id"],
                ),
                reverse=True,
            )
            latest_after = candidate_records[0] if candidate_records else None
            default_before = None
            if latest_after:
                after_instant = instants[latest_after["assessment_id"]][0]
                default_before = next(
                    (row for row in candidate_records
                     if instants[row["assessment_id"]][0] < after_instant),
                    None,
                )
            predecessor = None
            if side == "before" and after_assessment_id:
                after_instant = instants[after_assessment_id][0]
                predecessor = next(
                    (row for row in candidate_records
                     if instants[row["assessment_id"]][0] < after_instant),
                    None,
                )

            def public(row: dict | None) -> dict | None:
                if row is None:
                    return None
                metadata = self.assessment_context_metadata(
                    connection, row["assessment_id"]
                )
                return {
                    "assessmentId": row["assessment_id"],
                    "networkRosterRevision": row["network_roster_revision"],
                    "observationId": row["observation_id"],
                    "networkId": row["network_id"],
                    "networkName": row["network_name"],
                    "datasourceId": row["datasource_id"],
                    "datasetId": row["dataset_id"],
                    "observedAt": row["observed_at"],
                    "assessedAt": row["assessed_at"],
                    "completeness": row["completeness"],
                    **metadata,
                }

            selected_after = (
                by_id.get(after_assessment_id) if side == "before" else
                by_id.get(selected_assessment_id) if selected_assessment_id else latest_after
            )
            shortcuts = []
            if selected_after:
                for interval, duration_seconds in COMPARISON_INTERVALS.items():
                    try:
                        candidate = resolve_interval_candidate(
                            candidate_records, after_observed_at=selected_after["observed_at"],
                            interval=interval,
                        )
                    except ValueError as exc:
                        raise sqlite3.DatabaseError(
                            "Invalid stored health interval metadata"
                        ) from exc
                    shortcuts.append({
                        "interval": interval,
                        "durationSeconds": duration_seconds,
                        "candidate": public(candidate),
                    })

            return {
                "schemaVersion": 1,
                "networkId": network_id,
                "datasetId": dataset_id,
                "side": side,
                "afterAssessmentId": after_assessment_id,
                "total": len(candidates),
                "limit": limit,
                "offset": offset,
                "items": [public(row) for row in candidates[offset:offset + limit]],
                "selected": public(by_id.get(selected_assessment_id)),
                "defaultAfter": public(latest_after),
                "defaultBefore": public(default_before),
                "predecessor": public(predecessor),
                "selectedAfter": public(selected_after),
                "shortcuts": shortcuts,
            }

    @staticmethod
    def _comparison_page_on_connection(
        connection: sqlite3.Connection, *, comparison_id_value: str, limit: int,
        offset: int, scope: str, result: str,
    ) -> tuple[dict, list[dict]] | None:
        row = connection.execute(
            """SELECT c.*, EXISTS(SELECT 1 FROM observations o
               WHERE o.observation_id=c.before_observation_id) AS before_retained,
               EXISTS(SELECT 1 FROM observations o
               WHERE o.observation_id=c.after_observation_id) AS after_retained
               FROM comparisons c WHERE comparison_id=?""", (comparison_id_value,),
        ).fetchone()
        if row is None:
            return None
        header = dict(row)
        for side in ("before", "after"):
            header[f"{side}_context_metadata"] = (
                SQLiteHealthStore.assessment_context_metadata(
                    connection, row[f"{side}_assessment_id"]
                )
                if row[f"{side}_retained"]
                else None
            )
            if not row[f"{side}_retained"]:
                state = "pruned"
            else:
                schema_version = int(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    or 0
                )
                if schema_version < 8:
                    state = "preferred"
                else:
                    preference = (
                        SQLiteHealthStore.preferred_assessment_for_observation_on_connection(
                            connection, row[f"{side}_observation_id"]
                        )
                    )
                    state = (
                        "preferred"
                        if preference["assessment_id"]
                        == row[f"{side}_assessment_id"]
                        else "superseded"
                    )
            header[f"{side}_revision_state"] = state
        pruned = not row["before_retained"] or not row["after_retained"]
        effective_result = "CASE WHEN ? OR comparable=0 THEN 'unknown' ELSE change END"
        filters = []
        parameters: list[object] = []
        if scope != "all":
            filters.append("scope=?")
            parameters.append(scope)
        if result != "all":
            filters.append(f"{effective_result}=?")
            parameters.extend((pruned, result))
        where = " AND ".join(filters) or "1"
        count = connection.execute(
            f"SELECT COUNT(*) FROM comparison_items WHERE comparison_id=? AND {where}",
            (comparison_id_value, *parameters),
        ).fetchone()[0]
        items = connection.execute(
            f"""SELECT * FROM comparison_items WHERE comparison_id=? AND {where}
                ORDER BY scope, subject_id, item_kind, metric, item_id LIMIT ? OFFSET ?""",
            (comparison_id_value, *parameters, limit, offset),
        ).fetchall()
        return {**header, "filtered_item_count": count}, [dict(item) for item in items]

    def compare_endpoint_pair(
        self, *, network_id: str, dataset_id: str, before_assessment_id: str,
        after_assessment_id: str, limit: int, offset: int, scope: str, result: str,
    ) -> tuple[str, dict, list[dict]] | None:
        policy = ComparisonPolicy()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            endpoint_rows = {}
            for assessment_id_value in (before_assessment_id, after_assessment_id):
                row = connection.execute(
                    """SELECT a.assessment_id, o.observation_id, o.network_id,
                              o.dataset_id, o.observed_at
                       FROM assessments a JOIN observations o USING (observation_id)
                       WHERE a.assessment_id=?""", (assessment_id_value,),
                ).fetchone()
                if row is None:
                    return None
                endpoint_rows[assessment_id_value] = dict(row)
            before_row = endpoint_rows[before_assessment_id]
            after_row = endpoint_rows[after_assessment_id]
            if any(row["network_id"] != network_id or row["dataset_id"] != dataset_id
                   for row in endpoint_rows.values()):
                raise ValueError("Assessment endpoints must belong to the requested network and dataset")
            before_time = self._utc_instant(before_row["observed_at"])
            after_time = self._utc_instant(after_row["observed_at"])
            same_observation = before_row["observation_id"] == after_row["observation_id"]
            if not same_observation and before_time >= after_time:
                raise ValueError("Before assessment must precede After assessment")
            for source in connection.execute(
                """SELECT source_observed_at FROM observation_sources
                   WHERE observation_id IN (?, ?) AND source_observed_at IS NOT NULL""",
                (before_row["observation_id"], after_row["observation_id"]),
            ):
                self._utc_instant(source["source_observed_at"])
            deterministic_id = comparison_id(
                before_assessment_id, after_assessment_id, policy
            )
            stored = connection.execute(
                """SELECT 1 FROM comparisons WHERE comparison_id=?
                   AND comparison_version=? AND comparison_policy_digest=?""",
                (deterministic_id, COMPARISON_VERSION, policy.digest),
            ).fetchone()
            if stored:
                page = self._comparison_page_on_connection(
                    connection, comparison_id_value=deterministic_id, limit=limit,
                    offset=offset, scope=scope, result=result,
                )
                if page is not None:
                    return "stored", page[0], page[1]

            endpoint_metadata: dict[str, dict] = {}
            for side, endpoint_id in (
                ("before", before_assessment_id),
                ("after", after_assessment_id),
            ):
                endpoint_metadata[side] = self.assessment_context_metadata(
                    connection, endpoint_id
                )
                observation_id = endpoint_rows[endpoint_id]["observation_id"]
                schema_version = int(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    or 0
                )
                if schema_version < 8:
                    endpoint_metadata[f"{side}_revision_state"] = "preferred"
                else:
                    preference = self.preferred_assessment_for_observation_on_connection(
                        connection, observation_id
                    )
                    endpoint_metadata[f"{side}_revision_state"] = (
                        "preferred"
                        if preference["assessment_id"] == endpoint_id
                        else "superseded"
                    )
            before = self._endpoint(connection, before_assessment_id)
            after = self._endpoint(connection, after_assessment_id)
            if before is None or after is None:
                return None
            interval, items = self._derive_pair(connection, before, after)
            reset_states = {
                item.reset_evidence.state for item in items if item.reset_evidence
            }
            reset_state = (
                "reset-detected" if "reset-detected" in reset_states else
                "unknown" if "unknown" in reset_states else
                "same-epoch" if "same-epoch" in reset_states else
                "not-applicable"
            )
            return "derived", {
                "comparison_id": interval.comparison_id,
                "comparison_version": COMPARISON_VERSION,
                "before_assessment_id": interval.before_assessment_id,
                "after_assessment_id": interval.after_assessment_id,
                "before_context_metadata": endpoint_metadata["before"],
                "after_context_metadata": endpoint_metadata["after"],
                "before_revision_state": endpoint_metadata[
                    "before_revision_state"
                ],
                "after_revision_state": endpoint_metadata[
                    "after_revision_state"
                ],
                "before_observation_id": interval.baseline_observation_id,
                "after_observation_id": interval.after_observation_id,
                "before_observed_at": interval.before_observed_at,
                "after_observed_at": interval.after_observed_at,
                "network_id": network_id,
                "dataset_id": dataset_id,
                "datasource_id": after[0].datasource_id,
                "profile_id": after[1].profile_id,
                "source_signature": interval.source_signature,
                "sample_contract_version": after[1].sample_contract_version,
                "evaluator_version": after[1].evaluator_version,
                "before_assessment_digest": before[1].policy_digest,
                "after_assessment_digest": after[1].policy_digest,
                "endpoint_policy_digest": interval.endpoint_policy_digest,
                "comparison_policy_digest": interval.comparison_policy_digest,
                "elapsed_seconds": interval.elapsed_seconds,
                "gap_state": interval.gap_state,
                "reset_state": reset_state,
                "baseline_state": interval.baseline_state,
                "reset_witness_json": json.dumps({
                    item.item_id: {
                        "witness": item.reset_evidence.witness,
                        "before": item.reset_evidence.before_value,
                        "after": item.reset_evidence.after_value,
                    }
                    for item in items if item.reset_evidence
                }, sort_keys=True),
                "reasons_json": json.dumps(interval.compatibility.reasons),
                "comparable": int(interval.compatibility.comparable),
                "item_count": len(items),
                "created_at": None,
                "before_retained": 1,
                "after_retained": 1,
                "derived_items": items,
                "filtered_item_count": 0,
            }, []

    def roster_rows(self, *, network_id: str, limit: int, offset: int
                    ) -> tuple[list[dict], int]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            total = connection.execute(
                "SELECT COUNT(DISTINCT device_id) FROM device_last_known WHERE network_id=?",
                (network_id,),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT device_id FROM device_last_known WHERE network_id=?
                   GROUP BY device_id ORDER BY device_id LIMIT ? OFFSET ?""",
                (network_id, limit, offset),
            ).fetchall()
            return [self._roster_device_rows(connection, network_id, row["device_id"])
                    for row in rows], total

    def roster_snapshot(self, *, network_id: str, assessment_id: str) -> tuple[dict | None, list[dict], list[dict]]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            assessment = connection.execute(
                """SELECT a.assessment_id, o.observation_id, o.network_id, o.observed_at
                   FROM assessments a JOIN observations o USING (observation_id)
                   WHERE a.assessment_id=?""", (assessment_id,),
            ).fetchone()
            if assessment is None:
                return None, [], []
            if assessment["network_id"] != network_id:
                raise ValueError("Assessment does not belong to network")
            findings = [dict(row) for row in connection.execute(
                """SELECT rule_id, device_ids_json FROM findings WHERE assessment_id=?
                   AND scope='device' AND rule_id IN ('device.missing', 'device.offline')""",
                (assessment_id,),
            )]
            candidates = {row["device_id"]: {
                "deviceId": row["device_id"], "fields": [], "conflicts": [],
                "expectedLabel": None, "rosterState": "untracked",
                "lastEndpointPresenceAt": None, "observed": False,
            } for row in connection.execute(
                """SELECT device_id FROM device_last_known WHERE network_id=?
                   UNION SELECT device_id FROM expected_devices WHERE network_id=?
                   UNION SELECT device_id FROM device_samples WHERE observation_id=?""",
                (network_id, network_id, assessment["observation_id"]),
            )}
            for finding in findings:
                for device_id in json.loads(finding["device_ids_json"]):
                    candidates.setdefault(device_id, {
                        "deviceId": device_id, "fields": [], "conflicts": [],
                        "expectedLabel": None, "rosterState": "untracked",
                        "lastEndpointPresenceAt": None, "observed": False,
                    })
            for row in connection.execute(
                "SELECT device_id, label, roster_state FROM expected_devices WHERE network_id=?", (network_id,),
            ):
                candidates[row["device_id"]]["expectedLabel"] = row["label"]
                candidates[row["device_id"]]["rosterState"] = row["roster_state"]
            for row in connection.execute(
                "SELECT * FROM device_last_known WHERE network_id=? ORDER BY device_id, field_key", (network_id,),
            ):
                candidates[row["device_id"]]["fields"].append(dict(row))
            for row in connection.execute(
                """SELECT c.device_id, c.field_key, c.value_json, c.other_device_id,
                          c.source_observed_at, other.source_observed_at AS other_source_observed_at
                   FROM device_identity_conflicts c JOIN device_last_known other
                   ON other.network_id=c.network_id AND other.device_id=c.other_device_id
                   AND other.field_key=c.field_key AND other.value_json=c.value_json
                   WHERE c.network_id=?""", (network_id,),
            ):
                if row["device_id"] in candidates:
                    candidates[row["device_id"]]["conflicts"].append(dict(row))
            for row in connection.execute(
                """SELECT ds.device_id, MAX(o.observed_at) AS last_seen,
                          MAX(CASE WHEN ds.observation_id=? THEN 1 ELSE 0 END) AS observed
                   FROM device_samples ds JOIN observations o USING (observation_id)
                   WHERE o.network_id=? GROUP BY ds.device_id""",
                (assessment["observation_id"], network_id),
            ):
                if row["device_id"] in candidates:
                    candidates[row["device_id"]]["lastEndpointPresenceAt"] = row["last_seen"]
                    candidates[row["device_id"]]["observed"] = bool(row["observed"])
            return dict(assessment), list(candidates.values()), findings

    @staticmethod
    def _roster_device_rows(connection: sqlite3.Connection, network_id: str,
                            device_id: str) -> dict:
        rows = connection.execute(
            """SELECT * FROM device_last_known WHERE network_id=? AND device_id=? ORDER BY field_key""",
            (network_id, device_id),
        ).fetchall()
        expected_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(expected_devices)")
        }
        if {"updated_at", "revision", "reason", "expected_since", "change_source"} <= expected_columns:
            expected = connection.execute(
                """SELECT label, roster_state, updated_at, revision, reason, expected_since,
                          change_source FROM expected_devices
                   WHERE network_id=? AND device_id=?""",
                (network_id, device_id),
            ).fetchone()
        else:
            legacy = connection.execute(
                """SELECT label, roster_state FROM expected_devices
                   WHERE network_id=? AND device_id=?""",
                (network_id, device_id),
            ).fetchone()
            expected = ({
                "label": legacy["label"], "roster_state": legacy["roster_state"],
                "updated_at": None, "revision": 0, "reason": None,
                "expected_since": None, "change_source": "legacy",
            } if legacy else None)
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        network_revision_row = (
            connection.execute(
                "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                (network_id,),
            ).fetchone()
            if "network_roster_revisions" in tables else None
        )
        last_event = (
            connection.execute(
                """SELECT event_id, action, reason, occurred_at, origin, actor
                   FROM roster_lifecycle_events WHERE network_id=? AND device_id=?
                   ORDER BY occurred_at DESC, event_id DESC LIMIT 1""",
                (network_id, device_id),
            ).fetchone()
            if "roster_lifecycle_events" in tables else None
        )
        conflicts = connection.execute(
                """SELECT c.field_key, c.value_json, c.other_device_id, c.source_observed_at,
                    other.source_observed_at AS other_source_observed_at
                    FROM device_identity_conflicts c JOIN device_last_known other
                    ON other.network_id=c.network_id AND other.device_id=c.other_device_id
                    AND other.field_key=c.field_key AND other.value_json=c.value_json
                    WHERE c.network_id=? AND c.device_id=?""",
            (network_id, device_id),
        ).fetchall()
        presence = connection.execute(
            """SELECT MAX(o.observed_at) FROM device_samples ds JOIN observations o
               USING (observation_id) WHERE o.network_id=? AND ds.device_id=?""",
            (network_id, device_id),
        ).fetchone()[0]
        return {"deviceId": device_id, "fields": [dict(row) for row in rows],
                "expectedLabel": expected["label"] if expected else None,
            "rosterState": expected["roster_state"] if expected else "untracked",
            "designated": expected is not None,
                "revision": int(expected["revision"]) if expected else 0,
                "networkRosterRevision": (
                    int(network_revision_row["revision"]) if network_revision_row else 0
                ),
                "updatedAt": expected["updated_at"] if expected else None,
                "reason": expected["reason"] if expected else None,
                "expectedSince": expected["expected_since"] if expected else None,
                "changeSource": expected["change_source"] if expected else None,
                "lastLifecycleEvent": dict(last_event) if last_event else None,
                "conflicts": [dict(row) for row in conflicts], "lastEndpointPresenceAt": presence}

    def roster_device_row(
        self, *, network_id: str, device_id: str, assessment_id: str | None = None
    ) -> dict | None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            data = self._roster_device_rows(connection, network_id, device_id)
            if assessment_id is not None:
                assessment = connection.execute(
                    """SELECT a.assessment_id, o.observation_id, o.network_id
                       FROM assessments a JOIN observations o USING (observation_id)
                       WHERE a.assessment_id=?""",
                    (assessment_id,),
                ).fetchone()
                if assessment is None:
                    raise ValueError("Assessment not found")
                if assessment["network_id"] != network_id:
                    raise ValueError("Assessment does not belong to network")
                present = connection.execute(
                    """SELECT 1 FROM device_samples
                       WHERE observation_id=? AND device_id=?""",
                    (assessment["observation_id"], device_id),
                ).fetchone() is not None
                finding = connection.execute(
                    """SELECT rule_id FROM findings
                       WHERE assessment_id=? AND scope='device'
                         AND rule_id IN ('device.missing', 'device.offline')
                         AND EXISTS (SELECT 1 FROM json_each(findings.device_ids_json)
                                     WHERE json_each.value=?) LIMIT 1""",
                    (assessment_id, device_id),
                ).fetchone()
                data["contextAssessmentId"] = assessment_id
                data["contextObservationId"] = assessment["observation_id"]
                data["presenceState"] = (
                    "observed" if present else
                    finding["rule_id"].removeprefix("device.") if finding else "not-assessed"
                )
                return data if (
                    data["fields"] or data["designated"] or data["lastEndpointPresenceAt"] or present
                ) else None
            return data if data["fields"] or data["designated"] or data["lastEndpointPresenceAt"] else None

    def roster_label_candidates(self, *, network_id: str, label: str,
                                limit: int, offset: int) -> list[dict]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                """SELECT device_id FROM (
                     SELECT device_id FROM expected_devices WHERE network_id=? AND label=?
                     UNION
                     SELECT device_id FROM device_last_known WHERE network_id=?
                       AND field_key='deviceLabel' AND value_json=?
                   ) ORDER BY device_id LIMIT ? OFFSET ?""",
                (network_id, label, network_id, json.dumps(label, sort_keys=True, separators=(",", ":")),
                 limit, offset),
            ).fetchall()
            return [self._roster_device_rows(connection, network_id, row["device_id"])
                    for row in rows]

    def comparison_row(
        self, comparison_id: str, *, limit: int, offset: int,
        scope: str = "all", result: str = "all",
    ) -> tuple[dict, list[dict]] | None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            return self._comparison_page_on_connection(
                connection,
                comparison_id_value=comparison_id,
                limit=limit,
                offset=offset,
                scope=scope,
                result=result,
            )

    def _auto_compare(
        self,
        connection: sqlite3.Connection,
        observation: Observation,
        assessment: Assessment,
        *,
        allowed_assessment_ids: frozenset[str] | None = None,
        reserved_comparison_ids: frozenset[str] | None = None,
        enforce_retention: bool = True,
    ) -> tuple[int, int]:
        if observation.completeness is not Completeness.COMPLETE:
            return (0, 0)
        try:
            after_time = self._utc_instant(observation.observed_at)
        except sqlite3.DatabaseError:
            raise
        candidates = [
            dict(row) for row in connection.execute(
                """SELECT a.assessment_id, a.assessed_at, a.network_roster_revision,
                          o.observation_id, o.observed_at, o.completeness
                   FROM assessments a JOIN observations o USING (observation_id)
                   WHERE o.network_id=? AND o.dataset_id=?""",
                (observation.network_id, observation.dataset_id),
            )
        ]
        if allowed_assessment_ids is not None:
            candidates = [
                row for row in candidates
                if row["assessment_id"] in allowed_assessment_ids
            ]
        try:
            candidate_times = {
                row["assessment_id"]: (
                    self._utc_instant(row["observed_at"]),
                    self._utc_instant(row["assessed_at"]),
                )
                for row in candidates
            }
        except sqlite3.DatabaseError:
            raise
        if any(
            row["observation_id"] != observation.observation_id
            and candidate_times[row["assessment_id"]][0] == after_time
            for row in candidates
        ):
            return (0, 0)

        candidates.sort(
            key=lambda row: (
                candidate_times[row["assessment_id"]][0],
                row["network_roster_revision"],
                candidate_times[row["assessment_id"]][1],
                row["assessment_id"],
            ),
            reverse=True,
        )
        candidates = self.preferred_assessments_on_connection(
            connection, candidates
        )
        adjacent = next(
            (row for row in candidates
             if row["completeness"] == "complete"
             and candidate_times[row["assessment_id"]][0] < after_time),
            None,
        )
        target_ids = []
        if adjacent:
            target_ids.append(adjacent["assessment_id"])
        for interval in COMPARISON_INTERVALS:
            try:
                candidate = resolve_interval_candidate(
                    candidates, after_observed_at=observation.observed_at,
                    interval=interval, complete_only=True,
                )
            except ValueError as exc:
                raise sqlite3.DatabaseError(
                    "Invalid stored health interval metadata"
                ) from exc
            if candidate is not None:
                target_ids.append(candidate["assessment_id"])
        unique_target_ids = list(dict.fromkeys(target_ids))
        after: tuple[Observation, Assessment] | None = None
        policy = ComparisonPolicy()
        stored_count = 0
        deferred_count = 0
        for before_assessment_id in unique_target_ids:
            if allowed_assessment_ids is not None and (
                before_assessment_id not in allowed_assessment_ids
                or assessment.assessment_id not in allowed_assessment_ids
            ):
                continue
            expected_id = comparison_id(
                before_assessment_id, assessment.assessment_id, policy
            )
            present = connection.execute(
                """SELECT comparison_version, comparison_policy_digest
                   FROM comparisons WHERE comparison_id=?""",
                (expected_id,),
            ).fetchone()
            if present:
                if (present["comparison_version"] != COMPARISON_VERSION
                        or present["comparison_policy_digest"] != policy.digest):
                    raise sqlite3.DatabaseError(
                        "Stored health comparison identity has inconsistent policy metadata"
                    )
                continue
            if (
                reserved_comparison_ids is not None
                and expected_id not in reserved_comparison_ids
            ):
                deferred_count += 1
                continue
            if not enforce_retention and int(
                connection.execute(
                    "SELECT COUNT(*) FROM comparisons"
                ).fetchone()[0]
            ) >= 2000:
                deferred_count += 1
                continue
            before = self._endpoint(connection, before_assessment_id)
            if before is None:
                raise sqlite3.DatabaseError(
                    "Retained comparison baseline could not be reconstructed"
                )
            if after is None:
                after = self._endpoint(connection, assessment.assessment_id)
            if after is None:
                raise sqlite3.DatabaseError(
                    "Retained comparison endpoint could not be reconstructed"
                )
            interval, items = self._derive_pair(connection, before, after)
            if enforce_retention:
                self._store_comparison(
                    connection, before, after, interval, items
                )
            else:
                self._store_comparison(
                    connection,
                    before,
                    after,
                    interval,
                    items,
                    enforce_retention=False,
                )
            stored_count += 1
        return stored_count, deferred_count

    def reconcile_current_assessments(self, active_dataset_ids: tuple[str, ...]) -> int:
        if not active_dataset_ids:
            raise ValueError("At least one active dataset ID is required")
        placeholders = ", ".join("?" for _ in active_dataset_ids)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"DELETE FROM current_assessments WHERE dataset_id NOT IN ({placeholders})",
                active_dataset_ids,
            )
            connection.commit()
            return cursor.rowcount
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _insert_observation(
        self, connection: sqlite3.Connection, observation: Observation
    ) -> bool:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation.observation_id,
                observation.datasource_id,
                observation.dataset_id,
                observation.network_id,
                observation.network_name,
                observation.observed_at,
                observation.ingested_at,
                observation.completeness.value,
                observation.source_set_digest,
            ),
        )
        if cursor.rowcount == 0:
            return False
        connection.executemany(
            """INSERT INTO observation_sources
               (observation_id, filename, digest, kind, state, source_observed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                (
                    observation.observation_id,
                    source.filename,
                    source.digest,
                    source.kind,
                    source.state,
                    source.source_observed_at,
                )
                for source in observation.sources
            ),
        )
        for device in observation.devices:
            connection.execute(
                "INSERT OR IGNORE INTO devices(device_id, ext_address) VALUES (?, ?)",
                (device.device_id, device.ext_address),
            )
            connection.execute(
                "INSERT INTO device_samples VALUES (?, ?, ?, ?, ?, ?)",
                (
                    observation.observation_id,
                    device.device_id,
                    device.role,
                    device.state,
                    int(device.is_border_router),
                    json.dumps(device.source_files),
                ),
            )
        for relationship in observation.relationships:
            connection.execute(
                "INSERT OR IGNORE INTO relationships VALUES (?, ?, ?)",
                (
                    relationship.relationship_id,
                    relationship.from_device_id,
                    relationship.to_device_id,
                ),
            )
            connection.execute(
                     """INSERT INTO relationship_samples
                         (observation_id, relationship_id, relationship_type, link_quality_in,
                          link_quality_out, average_rssi, last_rssi, link_margin,
                          frame_error_rate, message_error_rate, reporter_device_id,
                          source_files_json, queued_message_count)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation.observation_id,
                    relationship.relationship_id,
                    relationship.relationship_type,
                    relationship.link_quality_in,
                    relationship.link_quality_out,
                    relationship.average_rssi,
                    relationship.last_rssi,
                    relationship.link_margin,
                    relationship.frame_error_rate,
                    relationship.message_error_rate,
                    relationship.reporter_device_id,
                    json.dumps(relationship.source_files),
                    relationship.queued_message_count,
                ),
            )
        connection.executemany(
            """INSERT INTO metric_samples
               (observation_id, device_id, metric, value, unit, denominator,
                source_file, metric_kind, denominator_kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    observation.observation_id,
                    metric.device_id,
                    metric.metric,
                    metric.value,
                    metric.unit,
                    metric.denominator,
                    metric.source_file,
                    METRIC_CATALOG.get(metric.metric, ("legacy-unknown", "", None, None))[0],
                    METRIC_CATALOG.get(metric.metric, ("", "", "legacy-unknown", None))[2] or "none",
                )
                for metric in observation.metrics
            ),
        )
        return True

    def _insert_assessment(
        self, connection: sqlite3.Connection, assessment: Assessment
    ) -> bool:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO assessments
               (assessment_id, observation_id, policy_version, policy_digest,
                evaluator_version, profile_id, status, confidence, coverage_json,
                assessed_at, sample_contract_version, health_policy_digest,
                roster_context_digest, network_roster_revision,
                presence_input_digest, reproduction_context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assessment.assessment_id,
                assessment.observation_id,
                assessment.policy_version,
                assessment.policy_digest,
                assessment.evaluator_version,
                assessment.profile_id,
                assessment.status.value,
                assessment.confidence.value,
                json.dumps(assessment.coverage, sort_keys=True),
                assessment.assessed_at,
                assessment.sample_contract_version,
                assessment.health_policy_digest,
                assessment.roster_context_digest,
                assessment.network_roster_revision,
                assessment.presence_input_digest,
                json.dumps(assessment.reproduction_context, sort_keys=True),
            ),
        )
        if cursor.rowcount == 0:
            return False
        connection.executemany(
            "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    assessment.assessment_id,
                    finding.finding_id,
                    finding.rule_id,
                    finding.status.value,
                    finding.scope.value,
                    int(finding.rank),
                    finding.title,
                    finding.summary,
                    finding.why_it_matters,
                    json.dumps(finding.evidence, sort_keys=True),
                    finding.confidence.value,
                    finding.action,
                    finding.verify,
                    json.dumps(finding.source_files),
                    json.dumps(finding.device_ids),
                    json.dumps(finding.relationship_ids),
                )
                for finding in assessment.findings
            ),
        )
        return True

    @staticmethod
    def _prior_complete_absences(
        connection: sqlite3.Connection,
        *,
        network_id: str,
        device_id: str,
        endpoint: tuple[datetime, str],
        expected_since: str | None,
    ) -> int:
        rows = connection.execute(
            """SELECT o.observation_id, o.observed_at,
                      EXISTS(SELECT 1 FROM device_samples ds
                             WHERE ds.observation_id=o.observation_id
                               AND ds.device_id=?) AS present
               FROM observations o
               WHERE o.network_id=? AND o.completeness='complete'""",
            (device_id, network_id),
        ).fetchall()
        epoch = SQLiteHealthStore._utc_instant(expected_since) if expected_since else None
        preceding = sorted(
            (
                (SQLiteHealthStore._utc_instant(row["observed_at"]), row["observation_id"], bool(row["present"]))
                for row in rows
                if (
                    SQLiteHealthStore._utc_instant(row["observed_at"]),
                    row["observation_id"],
                ) < endpoint
                and (epoch is None or SQLiteHealthStore._utc_instant(row["observed_at"]) >= epoch)
            ),
            reverse=True,
        )
        count = 0
        for _, _, present in preceding:
            if present:
                break
            count += 1
        return count

    @staticmethod
    def _retained_observation(
        connection: sqlite3.Connection, assessment_row: sqlite3.Row
    ) -> Observation:
        from td_health_manifest import load_health_manifest

        dataset = load_health_manifest().dataset(assessment_row["dataset_id"])
        safe_sources = {
            *dataset.files,
            dataset.health_profile.identity_file,
            *dataset.health_profile.required_outcomes,
        }

        def source_files(raw: str) -> tuple[str, ...]:
            try:
                values = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise sqlite3.DatabaseError("Invalid stored source filename list") from exc
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value in safe_sources for value in values
            ):
                raise sqlite3.DatabaseError("Stored sample references an undeclared source")
            return tuple(values)

        try:
            SQLiteHealthStore._utc_instant(assessment_row["observed_at"])
            SQLiteHealthStore._utc_instant(assessment_row["ingested_at"])
            completeness = Completeness(assessment_row["completeness"])
        except (ValueError, sqlite3.DatabaseError) as exc:
            raise sqlite3.DatabaseError("Invalid stored observation metadata") from exc
        sources = tuple(
            SourceEvidence(
                item["filename"], item["digest"], item["kind"], item["state"],
                item["source_observed_at"],
            )
            for item in connection.execute(
                """SELECT filename, digest, kind, state, source_observed_at
                   FROM observation_sources WHERE observation_id=? ORDER BY filename""",
                (assessment_row["observation_id"],),
            )
        )
        for item in sources:
            if item.filename not in safe_sources:
                raise sqlite3.DatabaseError("Stored observation references an undeclared source")
            if item.source_observed_at is not None:
                SQLiteHealthStore._utc_instant(item.source_observed_at)
        verified_source_digest = hashlib.sha256(
            "\0".join(
                f"{item.filename}:{item.digest}"
                for item in sorted(sources, key=lambda source: source.filename)
            ).encode("utf-8")
        ).hexdigest()
        if verified_source_digest != assessment_row["source_set_digest"]:
            raise sqlite3.DatabaseError("Stored observation source digest is inconsistent")
        devices: list[DeviceSample] = []
        for item in connection.execute(
            """SELECT device_id, role, state, is_border_router, source_files_json
               FROM device_samples WHERE observation_id=? ORDER BY device_id""",
            (assessment_row["observation_id"],),
        ):
            try:
                device_id = device_id_from_ext_address(
                    item["device_id"].removeprefix("extaddr:")
                )
            except ValueError as exc:
                raise sqlite3.DatabaseError("Invalid stored device identity") from exc
            if device_id != item["device_id"]:
                raise sqlite3.DatabaseError("Noncanonical stored device identity")
            devices.append(
                DeviceSample(
                    device_id,
                    device_id.removeprefix("extaddr:"),
                    item["role"],
                    item["state"],
                    bool(item["is_border_router"]),
                    source_files(item["source_files_json"]),
                )
            )
        relationships: list[RelationshipSample] = []
        for item in connection.execute(
            """SELECT rs.*, r.from_device_id, r.to_device_id
               FROM relationship_samples rs JOIN relationships r USING (relationship_id)
               WHERE rs.observation_id=? ORDER BY rs.relationship_id""",
            (assessment_row["observation_id"],),
        ):
            endpoints = (item["from_device_id"], item["to_device_id"])
            try:
                if any(
                    device_id_from_ext_address(
                        device_id.removeprefix("extaddr:")
                    ) != device_id
                    for device_id in endpoints
                ):
                    raise ValueError("noncanonical endpoint")
            except (AttributeError, ValueError) as exc:
                raise sqlite3.DatabaseError("Invalid stored relationship endpoint")
            if endpoints[0] == endpoints[1]:
                raise sqlite3.DatabaseError("Self relationship endpoint")
            numeric_values = (
                item["average_rssi"], item["last_rssi"], item["link_margin"],
                item["frame_error_rate"], item["message_error_rate"],
                item["queued_message_count"],
            )
            if any(
                value is not None and not math.isfinite(float(value))
                for value in numeric_values
            ):
                raise sqlite3.DatabaseError("Non-finite stored relationship sample")
            if item["queued_message_count"] is not None and item["queued_message_count"] < 0:
                raise sqlite3.DatabaseError("Negative stored queue count")
            if item["link_quality_in"] is not None and item["link_quality_in"] not in {0, 1, 2, 3}:
                raise sqlite3.DatabaseError("Invalid stored inbound link quality")
            if item["link_quality_out"] is not None and item["link_quality_out"] not in {0, 1, 2, 3}:
                raise sqlite3.DatabaseError("Invalid stored outbound link quality")
            relationships.append(
                RelationshipSample(
                    item["relationship_id"], item["relationship_type"],
                    item["from_device_id"], item["to_device_id"],
                    item["link_quality_in"], item["link_quality_out"],
                    item["average_rssi"], item["last_rssi"], item["link_margin"],
                    item["frame_error_rate"], item["message_error_rate"],
                    item["reporter_device_id"], source_files(item["source_files_json"]),
                    item["queued_message_count"],
                )
            )
        metrics: list[MetricSample] = []
        metric_units = {
            "route64Coverage": "flag",
            "totalMacErrorRatio": "ratio",
            "totalMacDiscardRatio": "ratio",
            "parentChanges": "count",
            "partitionIdChanges": "count",
            "betterPartitionAttachAttempts": "count",
            "totalParentPartitionChanges": "count",
            "routerRolePercent": "percent",
            "detachedDisabledPercent": "percent",
            "diagnosticTimeout": "flag",
            "observedLinkQuality1Count": "count",
            "observedLinkQuality2Count": "count",
            "observedLinkQuality3Count": "count",
        }
        mac_ratio_metrics = {"totalMacErrorRatio", "totalMacDiscardRatio"}
        for item in connection.execute(
            """SELECT device_id, metric, value, unit, denominator, source_file
               FROM metric_samples WHERE observation_id=?
               ORDER BY device_id, metric, source_file""",
            (assessment_row["observation_id"],),
        ):
            if (
                device_id_from_ext_address(
                    item["device_id"].removeprefix("extaddr:")
                ) != item["device_id"]
                or
                not math.isfinite(float(item["value"]))
                or item["denominator"] is not None
                and (
                    not math.isfinite(float(item["denominator"]))
                    or item["denominator"] < 0
                )
                or item["unit"] == "count" and item["value"] < 0
                or item["source_file"] not in safe_sources
            ):
                raise sqlite3.DatabaseError("Invalid stored metric sample")
            if metric_units.get(item["metric"]) != item["unit"]:
                raise sqlite3.DatabaseError("Stored metric unit does not match its contract")
            if (
                item["unit"] == "ratio"
                and (
                    item["denominator"] is None
                    or item["denominator"] <= 0
                    or item["value"] < 0
                    or item["metric"] not in mac_ratio_metrics
                    and item["value"] > 1
                )
                or item["unit"] == "percent"
                and not 0 <= item["value"] <= 100
                or item["unit"] == "flag" and item["value"] not in {0, 1}
            ):
                raise sqlite3.DatabaseError("Stored metric value is outside its contract")
            metrics.append(
                MetricSample(
                    item["device_id"], item["metric"], item["value"], item["unit"],
                    item["denominator"], item["source_file"],
                )
            )
        observation = Observation(
            assessment_row["observation_id"], assessment_row["datasource_id"],
            assessment_row["dataset_id"], assessment_row["network_id"],
            assessment_row["network_name"], assessment_row["observed_at"],
            assessment_row["ingested_at"], completeness,
            assessment_row["source_set_digest"], sources, tuple(devices),
            tuple(relationships), tuple(metrics),
        )
        try:
            source_signature(
                observation, source_roles_for_dataset(dataset)
            )
        except (UnsupportedSourceContractError, ValueError) as exc:
            raise sqlite3.DatabaseError(
                "Stored observation violates its approved source contract"
            ) from exc
        return observation

    @staticmethod
    def _reassessment_inputs(
        connection: sqlite3.Connection, assessment_id: str
    ) -> tuple[Observation, Assessment, object, object, dict, EvaluationInputs]:
        from td_health_evaluator import (
            EVALUATOR_VERSION,
            evaluation_inputs_from_payload,
        )
        from td_health_manifest import HealthProfile
        from td_health_policy import HealthPolicy

        row = connection.execute(
            """SELECT a.*, o.datasource_id, o.dataset_id, o.network_id,
                      o.network_name, o.observed_at, o.ingested_at, o.completeness,
                      o.source_set_digest
               FROM assessments a JOIN observations o USING (observation_id)
               WHERE a.assessment_id=?""",
            (assessment_id,),
        ).fetchone()
        if row is None:
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: current assessment is not retained"
            )
        try:
            context = json.loads(row["reproduction_context_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: saved evaluation context is invalid"
            ) from exc
        if (
            not isinstance(context, dict)
            or context.get("schemaVersion") != 2
            or context.get("evaluatorVersion") != EVALUATOR_VERSION
            or row["evaluator_version"] != EVALUATOR_VERSION
        ):
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: refresh health from retained snapshots before changing the roster"
            )
        policy_data = context.get("healthPolicy")
        profile_data = context.get("healthProfile")
        if not isinstance(policy_data, dict) or not isinstance(profile_data, dict):
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: saved policy or profile is missing"
            )
        try:
            policy = HealthPolicy(
                version=policy_data["version"],
                digest=policy_data["digest"],
                offline_consecutive_complete_observations=policy_data[
                    "offlineConsecutiveCompleteObservations"
                ],
                offline_poor_device_ratio_threshold=policy_data[
                    "offlinePoorDeviceRatioThreshold"
                ],
                thresholds=MappingProxyType({
                    metric: MappingProxyType(dict(bands))
                    for metric, bands in policy_data["thresholds"].items()
                }),
            )
            profile = HealthProfile(
                profile_id=profile_data["profileId"],
                identity_file=profile_data["identityFile"],
                required_outcomes=tuple(profile_data["requiredOutcomes"]),
                coverage=MappingProxyType(dict(profile_data["coverage"])),
                topology_authority=profile_data["topologyAuthority"],
                border_router_authority=profile_data["borderRouterAuthority"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: saved policy or profile is invalid"
            ) from exc
        if (
            profile.profile_id != row["profile_id"]
            or policy.digest != row["health_policy_digest"]
        ):
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: stored policy identity does not match its saved context"
            )
        try:
            evaluation_inputs = evaluation_inputs_from_payload(
                context.get("evaluationInputs")
            )
        except (TypeError, ValueError) as exc:
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: saved evaluation inputs are invalid"
            ) from exc
        if not isinstance(context.get("presenceInputs"), dict) or (
            context["presenceInputs"].get("sampleContractVersion")
            != row["sample_contract_version"]
        ):
            raise ReassessmentBaselineUnavailable(
                "reassessment-baseline-unavailable: saved sample contract is inconsistent"
            )

        observation = SQLiteHealthStore._retained_observation(connection, row)
        original = Assessment(
            assessment_id=row["assessment_id"],
            observation_id=row["observation_id"],
            policy_version=row["policy_version"],
            policy_digest=row["policy_digest"],
            evaluator_version=row["evaluator_version"],
            profile_id=row["profile_id"],
            status=HealthStatus(row["status"]),
            confidence=Confidence(row["confidence"]),
            coverage=json.loads(row["coverage_json"]),
            findings=(),
            assessed_at=row["assessed_at"],
            sample_contract_version=row["sample_contract_version"],
            health_policy_digest=row["health_policy_digest"],
            roster_context_digest=row["roster_context_digest"],
            presence_input_digest=row["presence_input_digest"],
            network_roster_revision=row["network_roster_revision"],
            reproduction_context=context,
        )
        return observation, original, policy, profile, context, evaluation_inputs

    def _reassess_network(
        self, connection: sqlite3.Connection, network_id: str
    ) -> list[dict]:
        from td_health_evaluator import (
            aggregate_assessment_state,
            evaluate_observation,
        )

        pointers = [
            dict(row) for row in connection.execute(
                """SELECT c.dataset_id, c.assessment_id
                   FROM current_assessments c
                   WHERE c.network_id=? ORDER BY c.dataset_id""",
                (network_id,),
            )
        ]
        current_revision_row = connection.execute(
            "SELECT revision FROM network_roster_revisions WHERE network_id=?",
            (network_id,),
        ).fetchone()
        network_revision = int(current_revision_row["revision"]) if current_revision_row else 0
        roster_records = [
            {
                "deviceId": row["device_id"],
                "rosterState": row["roster_state"],
                "revision": row["revision"],
                "expectedSince": row["expected_since"],
            }
            for row in connection.execute(
                """SELECT device_id, roster_state, revision, expected_since
                   FROM expected_devices WHERE network_id=? ORDER BY device_id""",
                (network_id,),
            )
        ]
        revisions: list[dict] = []
        for pointer in pointers:
            (
                observation,
                previous,
                policy,
                profile,
                old_context,
                old_evaluation_inputs,
            ) = self._reassessment_inputs(
                connection, pointer["assessment_id"]
            )
            if (
                old_evaluation_inputs.roster.state is EvaluationInputState.UNAVAILABLE
                or old_evaluation_inputs.absence_history.state
                is EvaluationInputState.UNAVAILABLE
            ):
                raise ReassessmentBaselineUnavailable(
                    "reassessment-baseline-unavailable: historical roster or absence context is unavailable; refresh health from retained snapshots"
                )
            endpoint = (self._utc_instant(observation.observed_at), observation.observation_id)
            old_roster = old_context.get("rosterContext", {}).get("records", [])
            old_records = {
                record.get("deviceId"): record
                for record in old_roster if isinstance(record, dict)
            }
            old_absences = old_context.get("priorCompleteAbsences", {})
            observed_ids = frozenset(device.device_id for device in observation.devices)
            expected_ids: set[str] = set()
            prior_absences: dict[str, int] = {}
            for record in roster_records:
                if record["rosterState"] != "expected":
                    continue
                epoch = (
                    self._utc_instant(record["expectedSince"])
                    if record["expectedSince"] is not None
                    else None
                )
                if epoch is not None and epoch > endpoint[0]:
                    continue
                device_id = record["deviceId"]
                expected_ids.add(device_id)
                if device_id in observed_ids or observation.completeness is not Completeness.COMPLETE:
                    continue
                old_record = old_records.get(device_id)
                unchanged = (
                    old_record is not None
                    and old_record.get("rosterState") == "expected"
                    and old_record.get("expectedSince") == record["expectedSince"]
                )
                if unchanged and isinstance(old_absences, dict):
                    count = old_absences.get(device_id, 0)
                    if type(count) is not int or count < 0:
                        raise ReassessmentBaselineUnavailable(
                            "reassessment-baseline-unavailable: saved absence history is invalid"
                        )
                    prior_absences[device_id] = count
                else:
                    prior_absences[device_id] = self._prior_complete_absences(
                        connection,
                        network_id=network_id,
                        device_id=device_id,
                        endpoint=endpoint,
                        expected_since=record["expectedSince"],
                    )
            roster_context = {
                "schemaVersion": 1,
                "networkId": network_id,
                "networkRosterRevision": network_revision,
                "records": roster_records,
            }
            evaluation_inputs = replace(
                old_evaluation_inputs,
                roster=EvaluationInputDomain(EvaluationInputState.AVAILABLE),
                expected_device_ids=frozenset(expected_ids),
                absence_history=EvaluationInputDomain(EvaluationInputState.AVAILABLE),
                prior_complete_absences=prior_absences,
                roster_context=roster_context,
                history_boundary=old_context.get("historyBoundary"),
            )
            revised = evaluate_observation(
                observation,
                policy,
                profile=profile,
                expected_device_ids=frozenset(expected_ids),
                prior_complete_absences=prior_absences,
                assessed_at=datetime.now(timezone.utc).isoformat(),
                roster_context=roster_context,
                network_roster_revision=network_revision,
                history_boundary=old_context.get("historyBoundary"),
                evaluation_inputs=evaluation_inputs,
                sample_contract_version=previous.sample_contract_version,
            )
            roster_rules = {
                "device.missing", "device.offline", "network.offline-impact",
                "observation.evaluation-context-unavailable",
            }
            previous_findings = [
                Finding(
                    item["finding_id"], item["rule_id"], HealthStatus(item["status"]),
                    FindingScope(item["scope"]), FindingRank(item["rank"]),
                    item["title"], item["summary"], item["why_it_matters"],
                    tuple(json.loads(item["device_ids_json"])),
                    tuple(json.loads(item["relationship_ids_json"])),
                    json.loads(item["evidence_json"]), Confidence(item["confidence"]),
                    item["action"], item["verify"], "", "",
                    tuple(json.loads(item["source_files_json"])),
                )
                for item in connection.execute(
                    "SELECT * FROM findings WHERE assessment_id=?",
                    (previous.assessment_id,),
                )
                if item["rule_id"] not in roster_rules
            ]
            revised_findings = tuple(sorted(
                previous_findings + [
                    finding for finding in revised.findings
                    if finding.rule_id in roster_rules
                ],
                key=lambda item: (-int(item.rank), item.finding_id),
            ))
            coverage = dict(revised.coverage)
            observed_pillars = coverage["observedPillars"]
            status, confidence = aggregate_assessment_state(
                revised_findings,
                completeness=observation.completeness,
                device_count=len(observation.devices),
                observed_pillars=observed_pillars,
                evaluation_inputs=evaluation_inputs,
            )
            assessment = replace(
                revised,
                findings=revised_findings,
                coverage=coverage,
                status=status,
                confidence=confidence,
            )
            assessment_created = self._insert_assessment(connection, assessment)
            self.consider_native_preference(
                connection, assessment.assessment_id
            )
            if assessment_created:
                self._auto_compare(connection, observation, assessment)
            self._set_current_assessment(
                connection, network_id, pointer["dataset_id"]
            )
            revisions.append({
                "datasetId": pointer["dataset_id"],
                "previousAssessmentId": previous.assessment_id,
                "assessmentId": assessment.assessment_id,
                "observationId": observation.observation_id,
            })
        return revisions

    def _prune_observations(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """DELETE FROM observations WHERE observation_id IN (
                   SELECT observation_id FROM observations
                   ORDER BY ingested_at DESC, observation_id DESC LIMIT -1 OFFSET ?
               )""",
            (self.max_observations,),
        )
        self._delete_orphans(connection)

    @staticmethod
    def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in _PURGE_TABLES
        }

    @staticmethod
    def consider_native_preference(
        connection: sqlite3.Connection,
        assessment_id: str,
        *,
        new_observation: bool = False,
    ) -> None:
        """Select a native assessment against the original lineage basis."""
        candidate = connection.execute(
            """SELECT assessment_id, observation_id, network_roster_revision,
                      assessed_at
               FROM assessments WHERE assessment_id=?""",
            (assessment_id,),
        ).fetchone()
        if candidate is None:
            raise sqlite3.DatabaseError("Native preference candidate is missing")
        preference = connection.execute(
            """SELECT observation_id, assessment_id,
                      selection_basis_assessment_id, origin, migration_id
               FROM health_assessment_preferences WHERE observation_id=?""",
            (candidate["observation_id"],),
        ).fetchone()
        if preference is None:
            if not new_observation:
                raise sqlite3.DatabaseError(
                    "Schema-8 assessment preference is missing for retained observation"
                )
            connection.execute(
                """INSERT INTO health_assessment_preferences
                   (observation_id, assessment_id, selection_basis_assessment_id,
                    origin, migration_id)
                   VALUES (?, ?, ?, 'native', NULL)""",
                (
                    candidate["observation_id"],
                    assessment_id,
                    assessment_id,
                ),
            )
            return
        basis = connection.execute(
            """SELECT observation_id, assessment_id, network_roster_revision,
                      assessed_at
               FROM assessments WHERE assessment_id=?""",
            (preference["selection_basis_assessment_id"],),
        ).fetchone()
        selected = connection.execute(
            """SELECT observation_id FROM assessments WHERE assessment_id=?""",
            (preference["assessment_id"],),
        ).fetchone()
        if (
            basis is None
            or selected is None
            or basis["observation_id"] != candidate["observation_id"]
            or selected["observation_id"] != candidate["observation_id"]
            or preference["origin"] == "native"
            and (
                preference["migration_id"] is not None
                or preference["assessment_id"]
                != preference["selection_basis_assessment_id"]
            )
            or preference["origin"] == "migration"
            and (
                preference["migration_id"] is None
                or connection.execute(
                    """SELECT 1 FROM health_assessment_upgrades
                       WHERE source_assessment_id=?
                         AND target_assessment_id=?
                         AND migration_id=?""",
                    (
                        preference["selection_basis_assessment_id"],
                        preference["assessment_id"],
                        preference["migration_id"],
                    ),
                ).fetchone()
                is None
            )
        ):
            raise sqlite3.DatabaseError("Corrupt native assessment preference")
        candidate_key = (
            int(candidate["network_roster_revision"]),
            SQLiteHealthStore._utc_instant(candidate["assessed_at"]),
            candidate["assessment_id"],
        )
        basis_key = (
            int(basis["network_roster_revision"]),
            SQLiteHealthStore._utc_instant(basis["assessed_at"]),
            basis["assessment_id"],
        )
        if candidate_key > basis_key:
            connection.execute(
                """UPDATE health_assessment_preferences
                   SET assessment_id=?, selection_basis_assessment_id=?,
                       origin='native', migration_id=NULL
                   WHERE observation_id=?""",
                (assessment_id, assessment_id, candidate["observation_id"]),
            )

    @staticmethod
    def preferred_assessments_on_connection(
        connection: sqlite3.Connection, rows: list[dict]
    ) -> list[dict]:
        """Select one verified preferred revision per observation."""
        schema_row = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        by_observation: dict[str, list[dict]] = {}
        for row in rows:
            by_observation.setdefault(row["observation_id"], []).append(row)
        if schema_row is None or int(schema_row[0] or 0) < 8:
            return [
                max(
                    candidates,
                    key=lambda row: (
                        int(row.get("network_roster_revision", 0)),
                        SQLiteHealthStore._utc_instant(row["assessed_at"]),
                        row["assessment_id"],
                    ),
                )
                for candidates in by_observation.values()
            ]
        preferred: list[dict] = []
        for observation_id, candidates in by_observation.items():
            preference = connection.execute(
                """SELECT assessment_id, selection_basis_assessment_id,
                          origin, migration_id
                   FROM health_assessment_preferences WHERE observation_id=?""",
                (observation_id,),
            ).fetchone()
            if preference is None:
                raise sqlite3.DatabaseError(
                    "Corrupt health store: assessment preference is missing"
                )
            selected = next(
                (
                    candidate for candidate in candidates
                    if candidate["assessment_id"] == preference["assessment_id"]
                ),
                None,
            )
            basis = connection.execute(
                """SELECT observation_id FROM assessments
                   WHERE assessment_id=?""",
                (preference["selection_basis_assessment_id"],),
            ).fetchone()
            if selected is None or basis is None or basis["observation_id"] != observation_id:
                raise sqlite3.DatabaseError(
                    "Corrupt health store: assessment preference crosses observations"
                )
            if preference["origin"] == "native":
                if (
                    preference["migration_id"] is not None
                    or preference["assessment_id"]
                    != preference["selection_basis_assessment_id"]
                ):
                    raise sqlite3.DatabaseError(
                        "Corrupt health store: native assessment lineage is invalid"
                    )
                selected.update(
                    {
                        "migration_source_assessment_id": None,
                        "migration_committed_at": None,
                    }
                )
            elif preference["origin"] == "migration":
                lineage = connection.execute(
                    """SELECT u.source_assessment_id, u.target_assessment_id,
                              u.migration_id, m.committed_at
                       FROM health_assessment_upgrades u
                       JOIN health_history_migrations m USING (migration_id)
                       WHERE u.source_assessment_id=?
                         AND u.target_assessment_id=?
                         AND u.migration_id=?""",
                    (
                        preference["selection_basis_assessment_id"],
                        preference["assessment_id"],
                        preference["migration_id"],
                    ),
                ).fetchone()
                if lineage is None:
                    raise sqlite3.DatabaseError(
                        "Corrupt health store: migrated assessment lineage is invalid"
                    )
                selected.update(
                    {
                        "migration_source_assessment_id": lineage[
                            "source_assessment_id"
                        ],
                        "migration_committed_at": lineage["committed_at"],
                    }
                )
            else:
                raise sqlite3.DatabaseError(
                    "Corrupt health store: assessment preference origin is invalid"
                )
            preferred.append(selected)
        return preferred

    @staticmethod
    def preferred_assessment_for_observation_on_connection(
        connection: sqlite3.Connection, observation_id: str
    ) -> dict:
        """Return a validated preferred endpoint without remapping pinned IDs."""
        candidates = [
            dict(row)
            for row in connection.execute(
                """SELECT a.assessment_id, a.assessed_at,
                          a.network_roster_revision, o.observation_id,
                          o.observed_at
                   FROM assessments a JOIN observations o USING (observation_id)
                   WHERE o.observation_id=?""",
                (observation_id,),
            )
        ]
        preferred = SQLiteHealthStore.preferred_assessments_on_connection(
            connection, candidates
        )
        if len(preferred) != 1:
            raise sqlite3.DatabaseError(
                "Corrupt health store: retained comparison endpoint has no preferred assessment"
            )
        return preferred[0]

    @staticmethod
    def _latest_assessment_id(
        connection: sqlite3.Connection, network_id: str, dataset_id: str
    ) -> str | None:
        rows = connection.execute(
            """SELECT a.assessment_id, a.assessed_at, a.network_roster_revision,
                      o.observation_id, o.observed_at
               FROM assessments a JOIN observations o USING (observation_id)
               WHERE o.network_id=? AND o.dataset_id=?""",
            (network_id, dataset_id),
        ).fetchall()
        preferred = SQLiteHealthStore.preferred_assessments_on_connection(
            connection, [dict(row) for row in rows]
        )
        if not preferred:
            return None
        latest = max(
            preferred,
            key=lambda row: (
                SQLiteHealthStore._utc_instant(row["observed_at"]),
                row["observation_id"],
            ),
        )
        return latest["assessment_id"]

    @staticmethod
    def _set_current_assessment(
        connection: sqlite3.Connection, network_id: str, dataset_id: str
    ) -> None:
        assessment_id = SQLiteHealthStore._latest_assessment_id(
            connection, network_id, dataset_id
        )
        if assessment_id is None:
            connection.execute(
                "DELETE FROM current_assessments WHERE network_id=? AND dataset_id=?",
                (network_id, dataset_id),
            )
            return
        connection.execute(
            """INSERT INTO current_assessments(network_id, dataset_id, assessment_id)
               VALUES (?, ?, ?)
               ON CONFLICT(network_id, dataset_id) DO UPDATE SET
                   assessment_id=excluded.assessment_id""",
            (network_id, dataset_id, assessment_id),
        )

    @staticmethod
    def _repair_current_assessments(connection: sqlite3.Connection) -> None:
        datasets = connection.execute(
            "SELECT DISTINCT network_id, dataset_id FROM observations"
        ).fetchall()
        for row in datasets:
            SQLiteHealthStore._set_current_assessment(
                connection, row["network_id"], row["dataset_id"]
            )

    @staticmethod
    def _delete_orphans(connection: sqlite3.Connection) -> None:
        connection.execute(
            """DELETE FROM device_last_known WHERE NOT EXISTS (
               SELECT 1 FROM device_samples ds JOIN observations o USING (observation_id)
               WHERE o.network_id=device_last_known.network_id
               AND ds.device_id=device_last_known.device_id)
               AND NOT EXISTS (SELECT 1 FROM expected_devices e
               WHERE e.network_id=device_last_known.network_id
               AND e.device_id=device_last_known.device_id)"""
        )
        connection.execute(
            """DELETE FROM device_identity_conflicts WHERE NOT EXISTS (
               SELECT 1 FROM device_last_known d WHERE d.network_id=device_identity_conflicts.network_id
               AND d.device_id=device_identity_conflicts.device_id
               AND d.field_key=device_identity_conflicts.field_key
               AND d.value_json=device_identity_conflicts.value_json)"""
        )
        connection.execute(
            """DELETE FROM relationships
               WHERE NOT EXISTS (
                   SELECT 1 FROM relationship_samples rs
                   WHERE rs.relationship_id=relationships.relationship_id
               )"""
        )
        connection.execute(
            """DELETE FROM devices
               WHERE NOT EXISTS (
                   SELECT 1 FROM device_samples ds WHERE ds.device_id=devices.device_id
               ) AND NOT EXISTS (
                   SELECT 1 FROM metric_samples ms WHERE ms.device_id=devices.device_id
               ) AND NOT EXISTS (
                   SELECT 1 FROM relationships r
                   WHERE r.from_device_id=devices.device_id
                      OR r.to_device_id=devices.device_id
               ) AND NOT EXISTS (
                   SELECT 1 FROM expected_devices e WHERE e.device_id=devices.device_id
               )"""
        )

    def purge_before(self, cutoff: datetime, *, dry_run: bool = False) -> PurgeResult:
        if cutoff.tzinfo is None:
            raise ValueError("Purge cutoff must include a timezone")
        cutoff_text = cutoff.astimezone(timezone.utc).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            before = self._table_counts(connection)
            connection.execute(
                "DELETE FROM observations WHERE julianday(observed_at) < julianday(?)",
                (cutoff_text,),
            )
            self._repair_current_assessments(connection)
            self._delete_orphans(connection)
            after = self._table_counts(connection)
            deleted = {table: before[table] - after[table] for table in _PURGE_TABLES}
            if dry_run:
                connection.rollback()
            else:
                connection.commit()
            return PurgeResult(cutoff=cutoff_text, deleted=deleted, dry_run=dry_run)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def purge_all(self, *, dry_run: bool = False) -> PurgeResult:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            before = self._table_counts(connection)
            connection.execute("DELETE FROM comparisons")
            connection.execute("DELETE FROM observations")
            connection.execute("DELETE FROM health_history_migrations")
            connection.execute("DELETE FROM expected_devices")
            connection.execute("DELETE FROM roster_mutation_receipts")
            connection.execute("DELETE FROM roster_lifecycle_events")
            connection.execute("DELETE FROM network_roster_revisions")
            self._delete_orphans(connection)
            after = self._table_counts(connection)
            deleted = {table: before[table] - after[table] for table in _PURGE_TABLES}
            if dry_run:
                connection.rollback()
            else:
                connection.commit()
            return PurgeResult(cutoff=None, deleted=deleted, dry_run=dry_run)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def purge_device(
        self,
        device_id: str,
        *,
        network_id: str | None = None,
        dry_run: bool = False,
    ) -> PurgeResult:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            networks = {
                row[0]
                for row in connection.execute(
                    """SELECT DISTINCT o.network_id
                       FROM observations o
                       JOIN device_samples ds ON ds.observation_id=o.observation_id
                       WHERE ds.device_id=?
                       UNION
                       SELECT network_id FROM expected_devices WHERE device_id=?
                       UNION
                       SELECT network_id FROM roster_lifecycle_events WHERE device_id=?""",
                    (device_id, device_id, device_id),
                )
            }
            referenced_observations: set[str] = set()
            assessment_query = """SELECT a.reproduction_context_json,
                                         o.observation_id, o.network_id
                                  FROM assessments a
                                  JOIN observations o USING (observation_id)"""
            assessment_parameters: tuple[object, ...] = ()
            if network_id is not None:
                assessment_query += " WHERE o.network_id=?"
                assessment_parameters = (network_id,)
            for row in connection.execute(
                assessment_query, assessment_parameters
            ):
                if device_id in _context_device_references(
                    row["reproduction_context_json"]
                ):
                    networks.add(row["network_id"])
                    referenced_observations.add(row["observation_id"])
            finding_query = """SELECT f.device_ids_json, o.observation_id,
                                      o.network_id
                               FROM findings f
                               JOIN assessments a USING (assessment_id)
                               JOIN observations o USING (observation_id)"""
            finding_parameters: tuple[object, ...] = ()
            if network_id is not None:
                finding_query += " WHERE o.network_id=?"
                finding_parameters = (network_id,)
            for row in connection.execute(finding_query, finding_parameters):
                if device_id in _finding_device_references(row["device_ids_json"]):
                    networks.add(row["network_id"])
                    referenced_observations.add(row["observation_id"])
            if network_id is None and len(networks) > 1:
                raise ValueError(
                    "Device exists in multiple networks; specify --network"
                )
            selected_network = network_id or (next(iter(networks)) if networks else None)
            before = self._table_counts(connection)
            values: tuple[object, ...]
            network_clause = ""
            if selected_network is None:
                values = (device_id,)
            else:
                network_clause = " AND o.network_id=?"
                values = (device_id, selected_network)
            affected_observations = {
                row[0]
                for row in connection.execute(
                    f"""SELECT DISTINCT o.observation_id
                        FROM observations o
                        WHERE (
                            EXISTS (SELECT 1 FROM device_samples ds
                                    WHERE ds.observation_id=o.observation_id
                                      AND ds.device_id=?)
                            OR EXISTS (SELECT 1 FROM metric_samples ms
                                       WHERE ms.observation_id=o.observation_id
                                         AND ms.device_id=?)
                            OR EXISTS (
                                SELECT 1 FROM relationship_samples rs
                                JOIN relationships r
                                  ON r.relationship_id=rs.relationship_id
                                WHERE rs.observation_id=o.observation_id
                                  AND (r.from_device_id=? OR r.to_device_id=?)
                            )
                        ){network_clause}""",
                    (device_id, device_id, device_id, device_id, *values[1:]),
                )
            }
            affected_observations.update(
                observation_id
                for observation_id in referenced_observations
                if selected_network is None
                or connection.execute(
                    "SELECT 1 FROM observations WHERE observation_id=? AND network_id=?",
                    (observation_id, selected_network),
                ).fetchone()
                is not None
            )
            affected_observations = sorted(affected_observations)
            if affected_observations:
                placeholders = ",".join("?" for _ in affected_observations)
                connection.execute(
                    f"""DELETE FROM comparisons WHERE before_observation_id IN ({placeholders})
                        OR after_observation_id IN ({placeholders})""",
                    (*affected_observations, *affected_observations),
                )
                connection.execute(
                    f"DELETE FROM assessments WHERE observation_id IN ({placeholders})",
                    affected_observations,
                )
                connection.execute(
                    f"DELETE FROM metric_samples WHERE device_id=? AND observation_id IN ({placeholders})",
                    (device_id, *affected_observations),
                )
                relationship_ids = [
                    row[0]
                    for row in connection.execute(
                        """SELECT relationship_id FROM relationships
                           WHERE from_device_id=? OR to_device_id=?""",
                        (device_id, device_id),
                    )
                ]
                if relationship_ids:
                    relationship_placeholders = ",".join("?" for _ in relationship_ids)
                    connection.execute(
                        f"DELETE FROM relationship_samples WHERE relationship_id IN ({relationship_placeholders}) "
                        f"AND observation_id IN ({placeholders})",
                        (*relationship_ids, *affected_observations),
                    )
                connection.execute(
                    f"DELETE FROM device_samples WHERE device_id=? AND observation_id IN ({placeholders})",
                    (device_id, *affected_observations),
                )
            if selected_network is None:
                connection.execute(
                    "DELETE FROM expected_devices WHERE device_id=?", (device_id,)
                )
                connection.execute(
                    """DELETE FROM roster_mutation_receipts
                       WHERE device_id=?""",
                    (device_id,),
                )
                connection.execute(
                    "DELETE FROM roster_lifecycle_events WHERE device_id=?", (device_id,)
                )
                connection.execute("DELETE FROM device_last_known WHERE device_id=?", (device_id,))
                connection.execute("DELETE FROM device_identity_conflicts WHERE device_id=? OR other_device_id=?",
                                   (device_id, device_id))
            else:
                removed_expectation = connection.execute(
                    "SELECT 1 FROM expected_devices WHERE device_id=? AND network_id=?",
                    (device_id, selected_network),
                ).fetchone()
                connection.execute(
                    "DELETE FROM expected_devices WHERE device_id=? AND network_id=?",
                    (device_id, selected_network),
                )
                connection.execute(
                    """DELETE FROM roster_mutation_receipts
                       WHERE network_id=? AND device_id=?""",
                    (selected_network, device_id),
                )
                connection.execute(
                    "DELETE FROM roster_lifecycle_events WHERE network_id=? AND device_id=?",
                    (selected_network, device_id),
                )
                connection.execute("DELETE FROM device_last_known WHERE device_id=? AND network_id=?",
                                   (device_id, selected_network))
                connection.execute("DELETE FROM device_identity_conflicts WHERE network_id=? AND (device_id=? OR other_device_id=?)",
                                   (selected_network, device_id, device_id))
                if removed_expectation:
                    current = connection.execute(
                        "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                        (selected_network,),
                    ).fetchone()
                    revision = int(current["revision"]) if current else 0
                    connection.execute(
                        """INSERT INTO network_roster_revisions(network_id, revision, updated_at)
                           VALUES (?, ?, ?) ON CONFLICT(network_id) DO UPDATE SET
                           revision=excluded.revision, updated_at=excluded.updated_at""",
                        (selected_network, revision + 1, datetime.now(timezone.utc).isoformat()),
                    )
            if selected_network is None:
                connection.execute("DELETE FROM device_fact_samples WHERE device_id=?", (device_id,))
            else:
                connection.execute(
                    """DELETE FROM device_fact_samples WHERE device_id=? AND observation_id IN
                       (SELECT observation_id FROM observations WHERE network_id=?)""",
                    (device_id, selected_network),
                )
            self._repair_current_assessments(connection)
            self._delete_orphans(connection)
            after = self._table_counts(connection)
            deleted = {table: before[table] - after[table] for table in _PURGE_TABLES}
            if dry_run:
                connection.rollback()
            else:
                connection.commit()
            return PurgeResult(cutoff=None, deleted=deleted, dry_run=dry_run)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def expected_device_ids(self, network_id: str) -> frozenset[str]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """SELECT device_id FROM expected_devices
                   WHERE network_id=? AND roster_state='expected'""",
                (network_id,),
            )
            return frozenset(row["device_id"] for row in rows)

    def roster_evaluation_inputs(
        self,
        *,
        network_id: str,
        observation_id: str,
        observed_at: str,
        completeness: Completeness,
        observed_device_ids: frozenset[str],
    ) -> dict:
        endpoint = self._utc_instant(observed_at)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            revision_row = connection.execute(
                "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                (network_id,),
            ).fetchone()
            network_revision = int(revision_row["revision"]) if revision_row else 0
            boundary_rows = connection.execute(
                """SELECT observation_id, observed_at FROM observations
                   WHERE network_id=? AND completeness='complete'""",
                (network_id,),
            ).fetchall()
            history_boundary = min(
                (
                    (self._utc_instant(row["observed_at"]), row["observation_id"])
                    for row in boundary_rows
                ),
                default=None,
            )
            roster_rows = [
                dict(row) for row in connection.execute(
                    """SELECT device_id, roster_state, revision, expected_since
                       FROM expected_devices WHERE network_id=? ORDER BY device_id""",
                    (network_id,),
                )
            ]
            context_records = [
                {
                    "deviceId": row["device_id"],
                    "rosterState": row["roster_state"],
                    "revision": row["revision"],
                    "expectedSince": row["expected_since"],
                }
                for row in roster_rows
            ]
            eligible_rows = []
            for row in roster_rows:
                if row["roster_state"] != "expected":
                    continue
                epoch = (
                    self._utc_instant(row["expected_since"])
                    if row["expected_since"] is not None
                    else None
                )
                if epoch is None or epoch <= endpoint:
                    eligible_rows.append((row["device_id"], epoch))
            expected_ids = frozenset(device_id for device_id, _ in eligible_rows)
            prior_absences: dict[str, int] = {}
            if completeness is Completeness.COMPLETE:
                absent_ids = expected_ids - observed_device_ids
                for device_id in absent_ids:
                    epoch = next(
                        eligible_epoch for eligible_id, eligible_epoch in eligible_rows
                        if eligible_id == device_id
                    )
                    rows = [
                        dict(row) for row in connection.execute(
                            """SELECT o.observation_id, o.observed_at,
                                      EXISTS(SELECT 1 FROM device_samples ds
                                             WHERE ds.observation_id=o.observation_id
                                               AND ds.device_id=?) AS present
                               FROM observations o
                               WHERE o.network_id=? AND o.completeness='complete'""",
                            (device_id, network_id),
                        )
                    ]
                    earlier = sorted(
                        (
                            (self._utc_instant(row["observed_at"]), row["observation_id"], bool(row["present"]))
                            for row in rows
                            if (
                                self._utc_instant(row["observed_at"]),
                                row["observation_id"],
                            ) < (endpoint, observation_id)
                            and (epoch is None or self._utc_instant(row["observed_at"]) >= epoch)
                        ),
                        reverse=True,
                    )
                    count = 0
                    for _, _, present in earlier:
                        if present:
                            break
                        count += 1
                    prior_absences[device_id] = count
            return {
                "expectedDeviceIds": expected_ids,
                "priorCompleteAbsences": prior_absences,
                "networkRosterRevision": network_revision,
                "rosterContext": {
                    "schemaVersion": 1,
                    "networkId": network_id,
                    "networkRosterRevision": network_revision,
                    "records": context_records,
                },
                "historyBoundary": (
                    {
                        "observedAt": history_boundary[0].isoformat(),
                        "observationId": history_boundary[1],
                    }
                    if history_boundary else None
                ),
            }

    def upsert_expected_device(
        self,
        network_id: str,
        device_id: str,
        label: str | None,
        roster_state: str | None = None,
    ) -> None:
        from td_health_roster_mutation import set_cli_roster_device

        set_cli_roster_device(
            self,
            network_id=network_id,
            device_id=device_id,
            label=label,
            state=roster_state,
            label_supplied=label is not None,
        )

    def expected_device_records(self, network_id: str) -> list[dict]:
        with closing(self._connect()) as connection, connection:
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT network_id, device_id, label, roster_state, updated_at,
                              revision, reason, expected_since, change_source
                       FROM expected_devices WHERE network_id=?
                       ORDER BY device_id""",
                    (network_id,),
                )
            ]

    def consecutive_complete_absences(
        self, network_id: str, device_id: str, before_observation_id: str
    ) -> int:
        with closing(self._connect()) as connection, connection:
            rows: Iterator[sqlite3.Row] = iter(
                connection.execute(
                    """SELECT o.observation_id,
                              EXISTS(SELECT 1 FROM device_samples ds
                                     WHERE ds.observation_id=o.observation_id
                                       AND ds.device_id=?) AS present
                       FROM observations o
                       WHERE o.network_id=? AND o.completeness='complete'
                         AND o.observation_id<>?
                       ORDER BY o.observed_at DESC, o.observation_id DESC""",
                    (device_id, network_id, before_observation_id),
                )
            )
            count = 0
            for row in rows:
                if row["present"]:
                    break
                count += 1
            return count

    def latest_assessment(self, network_id: str, dataset_id: str) -> dict | None:
        with closing(self._connect()) as connection, connection:
            assessment_id = self._latest_assessment_id(
                connection, network_id, dataset_id
            )
            if assessment_id is None:
                return None
            row = connection.execute(
                """SELECT a.*, o.network_id, o.network_name, o.datasource_id,
                          o.dataset_id, o.completeness, o.observed_at
                   FROM assessments a
                   JOIN observations o ON o.observation_id=a.observation_id
                   WHERE a.assessment_id=?""",
                (assessment_id,),
            ).fetchone()
            return dict(row) if row else None

    def assessment_record(
        self,
        *,
        dataset_id: str | None = None,
        network_id: str | None = None,
        assessment_id: str | None = None,
    ) -> dict | None:
        clauses: list[str] = []
        values: list[str] = []
        if assessment_id:
            clauses.append("a.assessment_id=?")
            values.append(assessment_id)
        if dataset_id:
            clauses.append("o.dataset_id=?")
            values.append(dataset_id)
        if network_id:
            clauses.append("o.network_id=?")
            values.append(network_id)
        where = " AND ".join(clauses) if clauses else "1=1"
        with closing(self._connect()) as connection, connection:
            rows = [
                dict(row)
                for row in connection.execute(
                f"""SELECT a.*, o.network_id, o.network_name, o.datasource_id,
                           o.dataset_id, o.completeness, o.observed_at,
                           o.ingested_at, o.source_set_digest
                    FROM assessments a
                    JOIN observations o ON o.observation_id=a.observation_id
                    WHERE {where}""",
                values,
                )
            ]
            if not rows:
                return None
            if assessment_id is None:
                rows = self.preferred_assessments_on_connection(
                    connection, rows
                )
            row = max(
                rows,
                key=lambda item: (
                    self._utc_instant(item["observed_at"]),
                    item["observation_id"],
                    self._utc_instant(item["assessed_at"]),
                    item["assessment_id"],
                ),
            )
            metadata = self.assessment_context_metadata(
                connection, row["assessment_id"]
            )
            row["evaluation_context_complete"] = metadata[
                "evaluationContextComplete"
            ]
            row["verdict_context_complete"] = metadata[
                "verdictContextComplete"
            ]
            row["unavailable_evaluation_domains"] = metadata[
                "unavailableEvaluationDomains"
            ]
            row["historical_roster_revision"] = metadata[
                "historicalRosterRevision"
            ]
            row["migration_source_assessment_id"] = (
                metadata["migration"]["sourceAssessmentId"]
                if metadata["migration"] is not None
                else None
            )
            row["migration_committed_at"] = (
                metadata["migration"]["committedAt"]
                if metadata["migration"] is not None
                else None
            )
            return row

    @staticmethod
    def _finding_filter(
        *,
        assessment_id: str,
        status: str | None,
        scope: str | None,
        device_id: str | None,
    ) -> tuple[str, list[object]]:
        clauses = ["assessment_id=?"]
        values: list[object] = [assessment_id]
        if status:
            clauses.append("status=?")
            values.append(status)
        if scope:
            clauses.append("scope=?")
            values.append(scope)
        if device_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(findings.device_ids_json) WHERE value=?)"
            )
            values.append(device_id)
        return " AND ".join(clauses), values

    def finding_records(
        self,
        assessment_id: str,
        *,
        status: str | None = None,
        scope: str | None = None,
        device_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        where, values = self._finding_filter(
            assessment_id=assessment_id,
            status=status,
            scope=scope,
            device_id=device_id,
        )
        page = ""
        if limit is not None:
            page = " LIMIT ? OFFSET ?"
            values.extend((limit, offset))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""SELECT * FROM findings WHERE {where}
                    ORDER BY rank DESC, finding_id ASC{page}""",
                values,
            )
            return [dict(row) for row in rows]

    def finding_count(
        self,
        assessment_id: str,
        *,
        status: str | None = None,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> int:
        where, values = self._finding_filter(
            assessment_id=assessment_id,
            status=status,
            scope=scope,
            device_id=device_id,
        )
        with closing(self._connect()) as connection, connection:
            return int(
                connection.execute(
                    f"SELECT COUNT(*) FROM findings WHERE {where}", values
                ).fetchone()[0]
            )

    def observation_records(
        self, *, network_id: str | None = None, limit: int = 25, offset: int = 0
    ) -> list[dict]:
        where = "WHERE network_id=?" if network_id else ""
        values: list[object] = [network_id] if network_id else []
        values.extend((limit, offset))
        with closing(self._connect()) as connection, connection:
            records = [
                dict(row) for row in connection.execute(
                f"""SELECT observation_id, datasource_id, dataset_id, network_id,
                           network_name, observed_at, ingested_at, completeness,
                           source_set_digest
                    FROM observations {where}
                    ORDER BY observed_at DESC, observation_id DESC
                    LIMIT ? OFFSET ?""",
                values,
                )
            ]
            if records:
                observation_ids = [row["observation_id"] for row in records]
                placeholders = ",".join("?" for _ in observation_ids)
                candidates = [
                    dict(row)
                    for row in connection.execute(
                        f"""SELECT a.assessment_id, a.assessed_at,
                                   a.network_roster_revision, o.observation_id,
                                   o.observed_at
                            FROM assessments a
                            JOIN observations o USING (observation_id)
                            WHERE o.observation_id IN ({placeholders})""",
                        observation_ids,
                    )
                ]
                preferred = {
                    row["observation_id"]: row["assessment_id"]
                    for row in self.preferred_assessments_on_connection(
                        connection, candidates
                    )
                }
                for row in records:
                    row["preferredAssessmentId"] = preferred.get(
                        row["observation_id"]
                    )
            return records

    def device_record(
        self, *, assessment_id: str, device_id: str
    ) -> dict | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """SELECT d.device_id, d.ext_address, ds.role, ds.state,
                          ds.is_border_router, ds.source_files_json,
                          o.observed_at, o.completeness
                   FROM assessments a
                   JOIN observations o ON o.observation_id=a.observation_id
                   JOIN device_samples ds ON ds.observation_id=o.observation_id
                   JOIN devices d ON d.device_id=ds.device_id
                   WHERE a.assessment_id=? AND d.device_id=?""",
                (assessment_id, device_id),
            ).fetchone()
            return dict(row) if row else None

    def store_capabilities(self) -> dict:
        with closing(self._connect()) as connection, connection:
            schema_version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            observation_count = connection.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
            assessment_count = connection.execute(
                "SELECT COUNT(*) FROM assessments"
            ).fetchone()[0]
            roster_count = connection.execute(
                "SELECT COUNT(*) FROM expected_devices WHERE roster_state='expected'"
            ).fetchone()[0]
        return {
            "schemaVersion": schema_version,
            "observationCount": observation_count,
            "assessmentCount": assessment_count,
            "expectedRosterCount": roster_count,
        }