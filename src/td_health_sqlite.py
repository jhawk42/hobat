"""Atomic SQLite backend for Thread health observations."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from td_health_observation_model import Assessment, Observation
from td_health_observation_store import (
    MAX_OBSERVATIONS,
    HealthStoreFutureSchemaError,
    PurgeResult,
    StoreResult,
)


SCHEMA_VERSION = 3
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

    def save_processing_result(
        self, observation: Observation, assessment: Assessment
    ) -> StoreResult:
        if assessment.observation_id != observation.observation_id:
            raise ValueError("Assessment and observation IDs do not match")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            observation_created = self._insert_observation(connection, observation)
            assessment_created = self._insert_assessment(connection, assessment)
            connection.execute(
                """INSERT INTO current_assessments(network_id, dataset_id, assessment_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(network_id, dataset_id) DO UPDATE SET assessment_id=excluded.assessment_id""",
                (observation.network_id, observation.dataset_id, assessment.assessment_id),
            )
            self._prune_observations(connection)
            connection.commit()
            return StoreResult(observation_created, assessment_created)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
            "INSERT INTO observation_sources VALUES (?, ?, ?, ?, ?)",
            (
                (
                    observation.observation_id,
                    source.filename,
                    source.digest,
                    source.kind,
                    source.state,
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
                "INSERT INTO relationship_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
        connection.executemany(
            "INSERT INTO metric_samples VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    observation.observation_id,
                    metric.device_id,
                    metric.metric,
                    metric.value,
                    metric.unit,
                    metric.denominator,
                    metric.source_file,
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
                assessed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            else:
                connection.execute(
                    "DELETE FROM expected_devices WHERE device_id=? AND network_id=?",
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