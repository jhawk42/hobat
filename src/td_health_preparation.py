"""Versioned derived health evidence; native samples remain authoritative."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import zlib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum

from td_health_comparison import ComparisonItem, Compatibility, ResetEvidence
from td_health_observation_model import (
    Completeness, DeviceSample, MetricSample, Observation, RelationshipSample,
    SourceEvidence,
)

VERSION = "health-preparation-v2"
CODEC = "json-arrays-zlib-1"
MAX_RECORDS = 2000
MAX_PAYLOAD_BYTES = 128 * 1024 * 1024
MAX_DECODE_BYTES = 64 * 1024 * 1024
LOG = logging.getLogger(__name__)
STATIC_ITEM_KINDS = frozenset({
    "counter-delta", "gauge-change", "ratio-change",
    "relationship-change", "queue-persistence",
})

OBSERVATION_COLUMNS = {
    "observation_id", "network_id", "sample_version", "contract_digest",
    "preparation_version", "input_digest", "codec", "payload_digest", "payload",
}
PAIR_COLUMNS = {
    "preparation_key", "network_id", "before_observation_id", "after_observation_id",
    "before_contract", "after_contract", "before_sample", "after_sample",
    "before_input", "after_input", "policy_digest", "preparation_version",
    "codec", "payload_digest", "payload",
}


class PreparationCorruptionError(sqlite3.DatabaseError):
    """Derived evidence contradicts its admitted immutable inputs."""


def plain(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(plain(value))).hexdigest()


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS health_observation_preparation (
        observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
        network_id TEXT NOT NULL, sample_version TEXT NOT NULL,
        contract_digest TEXT NOT NULL, preparation_version TEXT NOT NULL,
        input_digest TEXT NOT NULL, codec TEXT NOT NULL,
        payload_digest TEXT NOT NULL, payload BLOB NOT NULL,
        PRIMARY KEY(observation_id, sample_version, contract_digest, preparation_version))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS health_pair_preparation (
        preparation_key TEXT PRIMARY KEY NOT NULL, network_id TEXT NOT NULL,
        before_observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
        after_observation_id TEXT NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
        before_contract TEXT NOT NULL, after_contract TEXT NOT NULL,
        before_sample TEXT NOT NULL, after_sample TEXT NOT NULL,
        before_input TEXT NOT NULL, after_input TEXT NOT NULL,
        policy_digest TEXT NOT NULL, preparation_version TEXT NOT NULL,
        codec TEXT NOT NULL, payload_digest TEXT NOT NULL, payload BLOB NOT NULL)""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_health_prepared_observation_network "
                       "ON health_observation_preparation(network_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_health_prepared_pair_network "
                       "ON health_pair_preparation(network_id)")


def _values(sample) -> list:
    return [getattr(sample, field.name) for field in fields(sample)]


def _metadata(observation: Observation) -> list:
    return [observation.observation_id, observation.datasource_id, observation.dataset_id,
         observation.network_id, observation.network_name, observation.observed_at,
         observation.ingested_at, observation.completeness.value, observation.source_set_digest]


def _observation_payload(observation: Observation) -> list:
    return [
        _metadata(observation),
        [[*_values(sample)] for sample in observation.sources],
        [[*_values(sample)] for sample in observation.devices],
        [[*_values(sample)] for sample in observation.relationships],
        [[*_values(sample)] for sample in observation.metrics],
    ]


def _restore_observation(payload: list) -> Observation:
    metadata, sources, devices, relationships, metrics = payload
    metadata[7] = Completeness(metadata[7])
    for device in devices:
        device[5] = tuple(device[5])
    for relationship in relationships:
        relationship[12] = tuple(relationship[12])
    return Observation(
        *metadata, tuple(SourceEvidence(*row) for row in sources),
        tuple(DeviceSample(*row) for row in devices),
        tuple(RelationshipSample(*row) for row in relationships),
        tuple(MetricSample(*row) for row in metrics),
    )


_ITEM_CONTROL_FIELDS = (
    "scope", "kind", "metric", "unit", "denominator_kind", "direction", "change",
    "sample_count", "compatibility", "source_files", "before_source_time",
    "after_source_time", "transition", "reset_evidence", "relationship_type",
)


def _items_payload(items) -> list:
    templates, rows = [], []
    slots = {}
    for item in items:
        controls = [getattr(item, name) for name in _ITEM_CONTROL_FIELDS]
        # repr retains signed zero and numeric types in reset witnesses.
        key = (*controls[:13], repr(item.reset_evidence), controls[14])
        slot = slots.get(key)
        if slot is None:
            slot = len(templates)
            slots[key] = slot
            controls[8] = _values(item.compatibility)
            controls[13] = _values(item.reset_evidence) if item.reset_evidence is not None else None
            templates.append(controls)
        rows.append([slot, item.item_id, item.subject_id, item.before_value, item.after_value, item.delta])
    return [templates, rows]


def _restore_items(payload: list) -> tuple[ComparisonItem, ...]:
    templates, rows = payload
    for template in templates:
        if len(template) != len(_ITEM_CONTROL_FIELDS) or template[1] not in STATIC_ITEM_KINDS:
            raise ValueError("Invalid static comparison template")
        template[8] = Compatibility(*template[8][:4], tuple(template[8][4]))
        template[9] = tuple(template[9])
        template[13] = ResetEvidence(*template[13]) if template[13] is not None else None
    items = []
    for slot, item_id, subject_id, before, after, delta in rows:
        if type(slot) is not int or not 0 <= slot < len(templates):
            raise ValueError("Invalid static comparison template slot")
        control = templates[slot]
        items.append(ComparisonItem(
            item_id, control[0], subject_id, control[1], control[2], control[3],
            control[4], before, after, delta, control[5], control[6], control[7],
            control[8], control[9], control[10], control[11], control[12],
            control[13], control[14],
        ))
    return tuple(items)


class Preparation:
    def __init__(self, connection: sqlite3.Connection, network_id: str):
        self.connection = connection
        self.network_id = network_id
        self.stats: Counter[str] = Counter()
        self._contract_digests = {}
        self.available = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='health_observation_preparation'"
        ).fetchone() is not None
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        pair_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='health_pair_preparation'"
        ).fetchone() is not None
        if version >= 10 and (not self.available or not pair_table):
            raise PreparationCorruptionError("Health preparation schema is incomplete")

    def contract_digest(self, dataset) -> str:
        key = id(dataset)
        if key not in self._contract_digests:
            self._contract_digests[key] = (dataset, digest(dataset))
        return self._contract_digests[key][1]

    def event(self, name: str) -> None:
        self.stats[name] += 1
        LOG.info("Health preparation: %s", name)

    def _decode(self, row: sqlite3.Row):
        try:
            if row["network_id"] != self.network_id or row["codec"] != CODEC:
                raise ValueError("Preparation identity/codec mismatch")
            blob = row["payload"]
            if not isinstance(blob, bytes) or hashlib.sha256(blob).hexdigest() != row["payload_digest"]:
                raise ValueError("Preparation payload checksum mismatch")
            decoder = zlib.decompressobj()
            chunks, length, remaining = [], 0, blob
            while remaining:
                chunk = decoder.decompress(remaining, min(1024 * 1024, MAX_DECODE_BYTES + 1 - length))
                length += len(chunk)
                if length > MAX_DECODE_BYTES:
                    raise ValueError("Oversized preparation payload")
                chunks.append(chunk)
                remaining = decoder.unconsumed_tail
                if decoder.eof:
                    break
            if not decoder.eof or decoder.unused_data or remaining:
                raise ValueError("Invalid or oversized preparation payload")
            raw = b"".join(chunks)
            return json.loads(raw)
        except (ValueError, TypeError, zlib.error) as exc:
            raise PreparationCorruptionError("Invalid health preparation payload") from exc

    def observation_record(self, row, dataset):
        if not self.available:
            return None
        return self.connection.execute(
            """SELECT * FROM health_observation_preparation
               WHERE observation_id=? AND sample_version=? AND contract_digest=?
               AND preparation_version=?""",
            (row["observation_id"], row["sample_contract_version"], self.contract_digest(dataset), VERSION),
        ).fetchone()

    def load_observation(self, row, dataset, native_digest: Callable[[], str]):
        record = self.observation_record(row, dataset)
        if record is None:
            stale = self.available and self.connection.execute(
                "SELECT 1 FROM health_observation_preparation WHERE observation_id=?",
                (row["observation_id"],),
            ).fetchone() is not None
            self.event("observation-stale" if stale else "observation-missing")
            return None
        if record["input_digest"] != native_digest():
            raise PreparationCorruptionError("Prepared observation native inputs changed")
        try:
            observation = _restore_observation(self._decode(record))
            expected = (
                row["observation_id"], row["datasource_id"], row["dataset_id"],
                row["network_id"], row["network_name"], row["observed_at"],
                row["ingested_at"], row["completeness"], row["source_set_digest"],
            )
            if tuple(_metadata(observation)) != expected:
                raise ValueError("Prepared observation identity mismatch")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise PreparationCorruptionError("Invalid prepared observation") from exc
        self.event("observation-hit")
        return observation

    def _encode(self, payload):
        raw = canonical(payload)
        if len(raw) > MAX_DECODE_BYTES:
            self.event("publication-skipped-size")
            return None
        blob = zlib.compress(raw, 1)
        return CODEC, hashlib.sha256(blob).hexdigest(), blob

    def publish_observation(self, row, dataset, observation, native_digest: str) -> None:
        encoded = self._encode(_observation_payload(observation))
        if encoded is None:
            return
        self.connection.execute(
            "INSERT OR REPLACE INTO health_observation_preparation VALUES (?,?,?,?,?,?,?,?,?)",
            (observation.observation_id, self.network_id, row["sample_contract_version"],
             self.contract_digest(dataset), VERSION, native_digest, *encoded),
        )
        self.event("observation-published")
        self.trim()

    def load_pair(self, identity: dict, native_digests: Callable[[], tuple[str, str]]):
        if not self.available:
            self.event("pair-missing")
            return None
        key = digest(identity)
        row = self.connection.execute(
            "SELECT * FROM health_pair_preparation WHERE preparation_key=?", (key,),
        ).fetchone()
        if row is None:
            stale = self.connection.execute(
                """SELECT 1 FROM health_pair_preparation
                   WHERE before_observation_id=? AND after_observation_id=? LIMIT 1""",
                (identity["before_observation_id"], identity["after_observation_id"]),
            ).fetchone() is not None
            self.event("pair-stale" if stale else "pair-missing")
            return None
        if (row["network_id"] != self.network_id
                or any(row[name] != value for name, value in identity.items())
                or (row["before_input"], row["after_input"]) != native_digests()):
            raise PreparationCorruptionError("Prepared comparison identity/inputs changed")
        try:
            items = _restore_items(self._decode(row))
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise PreparationCorruptionError("Invalid prepared comparison") from exc
        self.event("pair-hit")
        return items

    def publish_pair(self, identity: dict, inputs: tuple[str, str], items) -> None:
        encoded = self._encode(_items_payload(items))
        if encoded is None:
            return
        self.connection.execute(
            """INSERT OR REPLACE INTO health_pair_preparation (
               preparation_key, network_id, before_observation_id, after_observation_id,
               before_contract, after_contract, before_sample, after_sample, before_input,
               after_input, policy_digest, preparation_version, codec, payload_digest, payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (digest(identity), self.network_id, identity["before_observation_id"],
             identity["after_observation_id"], identity["before_contract"],
             identity["after_contract"], identity["before_sample"], identity["after_sample"],
             *inputs, identity["policy_digest"], VERSION, *encoded),
        )
        self.event("pair-published")
        self.trim()

    def trim(self) -> None:
        for table, order, observation in (
            ("health_observation_preparation",
             "p.observation_id DESC, p.contract_digest DESC, p.sample_version DESC, p.preparation_version DESC",
             "observation_id"),
            ("health_pair_preparation", "p.preparation_key DESC", "after_observation_id"),
        ):
            self.connection.execute(
                f"""DELETE FROM {table} WHERE rowid IN (
                    SELECT p.rowid FROM {table} p JOIN observations o
                    ON o.observation_id=p.{observation} WHERE p.network_id=?
                    ORDER BY o.observed_at DESC, {order} LIMIT -1 OFFSET ?)""",
                (self.network_id, MAX_RECORDS),
            )
        while True:
            sizes = self.connection.execute(
                """SELECT coalesce(sum(length(payload)),0) FROM (
                   SELECT payload FROM health_observation_preparation WHERE network_id=?
                   UNION ALL SELECT payload FROM health_pair_preparation WHERE network_id=?)""",
                (self.network_id, self.network_id),
            ).fetchone()[0]
            if sizes <= MAX_PAYLOAD_BYTES:
                return
            oldest = self.connection.execute(
                """SELECT kind, id FROM (
                   SELECT 0 kind, p.rowid id, o.observed_at stamp,
                          p.observation_id || p.contract_digest || p.sample_version ||
                          p.preparation_version sort_key
                   FROM health_observation_preparation p JOIN observations o USING(observation_id)
                   WHERE p.network_id=?
                   UNION ALL SELECT 1, p.rowid, o.observed_at, p.preparation_key FROM health_pair_preparation p
                   JOIN observations o ON o.observation_id=p.after_observation_id WHERE p.network_id=?)
                   ORDER BY stamp, kind, sort_key LIMIT 1""", (self.network_id, self.network_id),
            ).fetchone()
            table = "health_pair_preparation" if oldest[0] else "health_observation_preparation"
            self.connection.execute(f"DELETE FROM {table} WHERE rowid=?", (oldest[1],))
            self.event("budget-eviction")
