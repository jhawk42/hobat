"""Atomic SQLite backend for Thread health observations."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from td_health_comparison import (
    COMPARISON_VERSION, METRIC_CATALOG, ROUTE64_SAMPLE_CONTRACT_VERSION,
    ComparisonItem, ComparisonInterval,
    derive_comparison, source_roles_for_dataset,
)
from td_health_manifest import load_health_manifest
from td_health_observation_model import (
    Assessment, Completeness, Confidence, DeviceSample, HealthStatus, MetricSample,
    Observation, RelationshipSample, SourceEvidence,
)
from td_health_observation_store import (
    MAX_OBSERVATIONS,
    HealthStoreFutureSchemaError,
    PurgeResult,
    StoreResult,
)
from td_health_roster import RosterFact


SCHEMA_VERSION = 4
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
    "comparisons",
    "comparison_items",
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
    UNIQUE (observation_id, policy_digest)
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
    PRIMARY KEY (network_id, device_id)
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

    def save_processing_result(
        self, observation: Observation, assessment: Assessment,
        *, roster_facts: tuple[RosterFact, ...] = (),
    ) -> StoreResult:
        if assessment.observation_id != observation.observation_id:
            raise ValueError("Assessment and observation IDs do not match")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            observation_created = self._insert_observation(connection, observation)
            if not observation_created and assessment.sample_contract_version == ROUTE64_SAMPLE_CONTRACT_VERSION:
                versions = {row[0] for row in connection.execute(
                    "SELECT DISTINCT sample_contract_version FROM assessments WHERE observation_id=?",
                    (observation.observation_id,),
                )}
                if versions != {ROUTE64_SAMPLE_CONTRACT_VERSION}:
                    raise ValueError("Cannot upgrade immutable observation samples to a new sample contract")
            if observation_created and roster_facts:
                self._insert_roster_facts(connection, observation, roster_facts)
            assessment_created = self._insert_assessment(connection, assessment)
            self._auto_compare(connection, observation, assessment)
            connection.execute(
                """INSERT INTO current_assessments(network_id, dataset_id, assessment_id)
                   SELECT ?, ?, a.assessment_id FROM assessments a
                   JOIN observations o USING (observation_id)
                   WHERE o.network_id=? AND o.dataset_id=?
                   ORDER BY o.observed_at DESC, a.assessed_at DESC, a.assessment_id DESC LIMIT 1
                   ON CONFLICT(network_id, dataset_id) DO UPDATE SET assessment_id=excluded.assessment_id""",
                (observation.network_id, observation.dataset_id,
                 observation.network_id, observation.dataset_id),
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
               AND field_key IN ('eui64', 'rloc16', 'routerId')
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
                          items: tuple[ComparisonItem, ...]) -> str:
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
            return [dict(row) for row in rows], total

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

    @staticmethod
    def _roster_device_rows(connection: sqlite3.Connection, network_id: str,
                            device_id: str) -> dict:
        rows = connection.execute(
            """SELECT * FROM device_last_known WHERE network_id=? AND device_id=? ORDER BY field_key""",
            (network_id, device_id),
        ).fetchall()
        expected = connection.execute(
            "SELECT label FROM expected_devices WHERE network_id=? AND device_id=?",
            (network_id, device_id),
        ).fetchone()
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
                "conflicts": [dict(row) for row in conflicts], "lastEndpointPresenceAt": presence}

    def roster_device_row(self, *, network_id: str, device_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            data = self._roster_device_rows(connection, network_id, device_id)
            return data if data["fields"] else None

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

    def comparison_row(self, comparison_id: str, *, limit: int, offset: int
                       ) -> tuple[dict, list[dict]] | None:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                """SELECT c.*, EXISTS(SELECT 1 FROM observations o
                   WHERE o.observation_id=c.before_observation_id) AS before_retained,
                   EXISTS(SELECT 1 FROM observations o
                   WHERE o.observation_id=c.after_observation_id) AS after_retained
                   FROM comparisons c WHERE comparison_id=?""", (comparison_id,),
            ).fetchone()
            if row is None:
                return None
            items = connection.execute(
                """SELECT * FROM comparison_items WHERE comparison_id=?
                   ORDER BY scope, subject_id, item_kind, metric, item_id LIMIT ? OFFSET ?""",
                (comparison_id, limit, offset),
            ).fetchall()
            return dict(row), [dict(item) for item in items]

    def _auto_compare(self, connection: sqlite3.Connection, observation: Observation,
                      assessment: Assessment) -> None:
        duplicate = connection.execute(
            """SELECT 1 FROM observations WHERE network_id=? AND dataset_id=?
               AND observed_at=? AND observation_id<>? LIMIT 1""",
            (observation.network_id, observation.dataset_id, observation.observed_at,
             observation.observation_id),
        ).fetchone()
        if duplicate:
            return
        baseline = connection.execute(
            """SELECT a.assessment_id FROM assessments a JOIN observations o USING (observation_id)
               WHERE o.network_id=? AND o.dataset_id=? AND o.completeness='complete'
               AND o.observed_at<? ORDER BY o.observed_at DESC, a.assessed_at DESC,
               a.assessment_id DESC LIMIT 1""",
            (observation.network_id, observation.dataset_id, observation.observed_at),
        ).fetchone()
        if baseline and observation.completeness is Completeness.COMPLETE:
            before = self._endpoint(connection, baseline["assessment_id"])
            after = self._endpoint(connection, assessment.assessment_id)
            if before and after:
                interval, items = self._derive_pair(connection, before, after)
                if not connection.execute(
                    "SELECT 1 FROM comparisons WHERE comparison_id=?", (interval.comparison_id,),
                ).fetchone():
                    self._store_comparison(connection, before, after, interval, items)

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
                assessed_at, sample_contract_version, health_policy_digest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
    def _repair_current_assessments(connection: sqlite3.Connection) -> None:
        connection.execute(
            """INSERT INTO current_assessments(network_id, dataset_id, assessment_id)
               SELECT o.network_id, o.dataset_id, a.assessment_id
               FROM assessments a
               JOIN observations o ON o.observation_id=a.observation_id
               WHERE a.assessment_id=(
                   SELECT a2.assessment_id
                   FROM assessments a2
                   JOIN observations o2 ON o2.observation_id=a2.observation_id
                   WHERE o2.network_id=o.network_id AND o2.dataset_id=o.dataset_id
                   ORDER BY o2.observed_at DESC, a2.assessed_at DESC,
                            a2.assessment_id DESC LIMIT 1
               )
               ON CONFLICT(network_id, dataset_id) DO NOTHING"""
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
            connection.execute("DELETE FROM expected_devices")
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
                       SELECT network_id FROM expected_devices WHERE device_id=?""",
                    (device_id, device_id),
                )
            }
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
            affected_observations = [
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
            ]
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
                connection.execute("DELETE FROM device_last_known WHERE device_id=?", (device_id,))
                connection.execute("DELETE FROM device_identity_conflicts WHERE device_id=? OR other_device_id=?",
                                   (device_id, device_id))
            else:
                connection.execute(
                    "DELETE FROM expected_devices WHERE device_id=? AND network_id=?",
                    (device_id, selected_network),
                )
                connection.execute("DELETE FROM device_last_known WHERE device_id=? AND network_id=?",
                                   (device_id, selected_network))
                connection.execute("DELETE FROM device_identity_conflicts WHERE network_id=? AND (device_id=? OR other_device_id=?)",
                                   (selected_network, device_id, device_id))
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

    def upsert_expected_device(
        self,
        network_id: str,
        device_id: str,
        label: str | None,
        roster_state: str = "expected",
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO expected_devices(network_id, device_id, label, roster_state)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(network_id, device_id) DO UPDATE SET
                       label=COALESCE(excluded.label, expected_devices.label),
                       roster_state=excluded.roster_state,
                       updated_at=CURRENT_TIMESTAMP""",
                (network_id, device_id, label, roster_state),
            )

    def expected_device_records(self, network_id: str) -> list[dict]:
        with closing(self._connect()) as connection, connection:
            return [
                dict(row)
                for row in connection.execute(
                    """SELECT network_id, device_id, label, roster_state, updated_at
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
            row = connection.execute(
                """SELECT a.*, o.network_id, o.network_name, o.datasource_id,
                          o.dataset_id, o.completeness, o.observed_at
                   FROM current_assessments c
                   JOIN assessments a ON a.assessment_id=c.assessment_id
                   JOIN observations o ON o.observation_id=a.observation_id
                   WHERE c.network_id=? AND c.dataset_id=?""",
                (network_id, dataset_id),
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
            row = connection.execute(
                f"""SELECT a.*, o.network_id, o.network_name, o.datasource_id,
                           o.dataset_id, o.completeness, o.observed_at,
                           o.ingested_at, o.source_set_digest
                    FROM assessments a
                    JOIN observations o ON o.observation_id=a.observation_id
                    WHERE {where}
                    ORDER BY o.observed_at DESC, a.assessed_at DESC,
                             a.assessment_id DESC
                    LIMIT 1""",
                values,
            ).fetchone()
            return dict(row) if row else None

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
            rows = connection.execute(
                f"""SELECT observation_id, datasource_id, dataset_id, network_id,
                           network_name, observed_at, ingested_at, completeness,
                           source_set_digest
                    FROM observations {where}
                    ORDER BY observed_at DESC, observation_id DESC
                    LIMIT ? OFFSET ?""",
                values,
            )
            return [dict(row) for row in rows]

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