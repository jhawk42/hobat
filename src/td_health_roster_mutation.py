"""Validated, transactional writes for operator-managed health expectations."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence

from merge_extaddr_device_label_map import normalize_valid_device_label
from td_health_observation_model import device_id_from_ext_address

if TYPE_CHECKING:
    from td_health_sqlite import SQLiteHealthStore


_NETWORK_ID = re.compile(r"^extpan:[0-9a-f]{16}$")
_ROSTER_STATES = frozenset({
    "expected", "intentionally-offline", "intermittent", "retired",
})


class RosterMutationConflictError(RuntimeError):
    """Raised when a roster action conflicts with current state or revision."""


class RosterMutationNotFoundError(LookupError):
    """Raised when an action requires a missing network-scoped resource."""


@dataclass(frozen=True)
class RosterDeviceMutation:
    network_id: str
    device_id: str
    changed: bool
    roster_state: str
    label: str | None
    revision: int
    network_roster_revision: int
    updated_at: str
    expected_since: str | None
    event_id: str | None
    reassessment: tuple[dict, ...] = ()


@dataclass(frozen=True)
class RosterImportResult:
    network_id: str
    imported: int
    already_present: int
    skipped: int


def _validate_network_id(value: str) -> str:
    if not isinstance(value, str) or not _NETWORK_ID.fullmatch(value):
        raise ValueError("networkId must be a canonical extpan identifier")
    return value


def _validate_device_id(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("extaddr:"):
        raise ValueError("deviceId must be a canonical extaddr identifier")
    canonical = device_id_from_ext_address(value.removeprefix("extaddr:"))
    if canonical != value:
        raise ValueError("deviceId must be a canonical extaddr identifier")
    return canonical


def _normalize_state(value: str | None) -> str | None:
    if value is not None and value not in _ROSTER_STATES:
        raise ValueError(f"Unsupported roster state: {value}")
    return value


def _normalize_label(value: str | None, *, supplied: bool) -> str | None:
    if not supplied:
        return None
    if value is None:
        raise ValueError("deviceLabel must be a string")
    return normalize_valid_device_label(value)


def set_cli_roster_device(
    store: SQLiteHealthStore,
    *,
    network_id: str,
    device_id: str,
    label: str | None,
    state: str | None,
    label_supplied: bool,
) -> RosterDeviceMutation:
    network_id = _validate_network_id(network_id)
    device_id = _validate_device_id(device_id)
    state = _normalize_state(state)
    label = _normalize_label(label, supplied=label_supplied)
    return _apply_changes(
        store,
        network_id=network_id,
        changes=((device_id, label, label_supplied, state),),
        origin="cli",
        actor="cli",
        insert_only=False,
    )[0]


def apply_browser_roster_action(
    store: SQLiteHealthStore,
    *,
    network_id: str,
    device_id: str,
    action: str,
    request_id: str,
    expected_revision: int,
    context_assessment_id: str | None,
    device_label: str | None,
    reason: str | None,
) -> tuple[dict, bool]:
    """Apply one idempotent, network-scoped browser action and reassess atomically."""
    network_id = _validate_network_id(network_id)
    device_id = _validate_device_id(device_id)
    digest_payload = {
        "action": action, "contextAssessmentId": context_assessment_id,
        "deviceLabel": device_label, "expectedRevision": expected_revision,
        "deviceId": device_id, "networkId": network_id, "reason": reason,
    }
    request_digest = hashlib.sha256(json.dumps(
        digest_payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    connection = store._connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        receipt = connection.execute(
            """SELECT request_digest, response_json FROM roster_mutation_receipts
               WHERE network_id=? AND request_id=?""",
            (network_id, request_id),
        ).fetchone()
        if receipt is not None:
            if receipt["request_digest"] != request_digest:
                raise RosterMutationConflictError("request-id-reused")
            response = json.loads(receipt["response_json"])
            connection.rollback()
            return response, False

        context_observation_id = None
        if context_assessment_id is not None:
            context = connection.execute(
                """SELECT o.observation_id, o.network_id FROM assessments a
                   JOIN observations o USING (observation_id)
                   WHERE a.assessment_id=?""",
                (context_assessment_id,),
            ).fetchone()
            if context is None:
                raise RosterMutationNotFoundError("context-assessment-not-found")
            if context["network_id"] != network_id:
                raise RosterMutationConflictError("context-network-mismatch")
            context_observation_id = context["observation_id"]
        if action == "enroll" and context_observation_id is None:
            raise RosterMutationConflictError("observation-context-required")

        existing = connection.execute(
            """SELECT label, roster_state, revision, updated_at, expected_since, reason
               FROM expected_devices WHERE network_id=? AND device_id=?""",
            (network_id, device_id),
        ).fetchone()
        if action == "enroll" and existing is None:
            candidate = connection.execute(
                """SELECT 1 FROM device_samples
                   WHERE observation_id=? AND device_id=? LIMIT 1""",
                (context_observation_id, device_id),
            ).fetchone()
            if candidate is None:
                raise RosterMutationNotFoundError("device-not-found-in-network-context")
        revision_row = connection.execute(
            "SELECT revision FROM network_roster_revisions WHERE network_id=?",
            (network_id,),
        ).fetchone()
        network_revision = int(revision_row["revision"]) if revision_row else 0
        current_revision = int(existing["revision"]) if existing else 0
        if current_revision != expected_revision:
            raise RosterMutationConflictError("stale-revision")

        targets = {
            "enroll": "expected",
            "mark-offline": "intentionally-offline",
            "clear-offline": "expected",
            "retire": "retired",
            "unretire": "expected",
        }
        if action not in targets:
            raise ValueError("Unsupported roster action")
        target = targets[action]
        already_target = existing is not None and existing["roster_state"] == target
        if action == "enroll":
            if existing and not already_target:
                raise RosterMutationConflictError("already-tracked")
            if existing and device_label is not None and device_label != existing["label"]:
                raise RosterMutationConflictError("enrollment-label-conflict")
        elif existing is None:
            raise RosterMutationNotFoundError("roster-device-not-found")
        elif not already_target and action == "mark-offline" and existing["roster_state"] != "expected":
            raise RosterMutationConflictError("invalid-transition")
        elif not already_target and action == "clear-offline" and existing["roster_state"] != "intentionally-offline":
            raise RosterMutationConflictError("invalid-transition")
        elif not already_target and action == "retire" and existing["roster_state"] not in (
            "expected", "intentionally-offline", "intermittent",
        ):
            raise RosterMutationConflictError("invalid-transition")
        elif not already_target and action == "unretire" and existing["roster_state"] != "retired":
            raise RosterMutationConflictError("invalid-transition")

        changed = existing is None or existing["roster_state"] != target
        now = datetime.now(timezone.utc).isoformat()
        event_id = None
        if changed:
            next_label = (
                device_label or f"found-{device_id.removeprefix('extaddr:')}"
                if action == "enroll" else existing["label"]
            )
            next_epoch = (
                now if target == "expected" and
                (existing is None or existing["roster_state"] != "expected")
                else existing["expected_since"] if existing else None
            )
            device_revision = current_revision + 1
            network_revision += 1
            connection.execute(
                """INSERT INTO network_roster_revisions(network_id, revision, updated_at)
                   VALUES (?, ?, ?) ON CONFLICT(network_id) DO UPDATE SET
                   revision=excluded.revision, updated_at=excluded.updated_at""",
                (network_id, network_revision, now),
            )
            connection.execute(
                """INSERT INTO expected_devices
                   (network_id, device_id, label, roster_state, updated_at, revision,
                    reason, expected_since, change_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'browser')
                   ON CONFLICT(network_id, device_id) DO UPDATE SET
                   label=excluded.label, roster_state=excluded.roster_state,
                   updated_at=excluded.updated_at, revision=excluded.revision,
                   reason=excluded.reason, expected_since=excluded.expected_since,
                   change_source=excluded.change_source""",
                (network_id, device_id, next_label, target, now, device_revision,
                 reason, next_epoch),
            )
            event_id = f"roster-event:{uuid.uuid4()}"
            connection.execute(
                """INSERT INTO roster_lifecycle_events
                   (event_id, request_id, network_id, device_id, action, from_state,
                    to_state, previous_label, new_label, previous_expected_since,
                    new_expected_since, reason, occurred_at, origin, actor,
                    context_assessment_id, context_observation_id, evidence_basis,
                    device_revision, network_revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'browser',
                           'dashboard', ?, ?, NULL, ?, ?)""",
                (event_id, request_id, network_id, device_id, action,
                 existing["roster_state"] if existing else None, target,
                 existing["label"] if existing else None, next_label,
                 existing["expected_since"] if existing else None, next_epoch,
                 reason, now, context_assessment_id, context_observation_id,
                 device_revision, network_revision),
            )
            reassessed = store._reassess_network(connection, network_id)
            reassessment = {"state": "complete", "assessments": reassessed}
        else:
            next_label = existing["label"]
            device_revision = current_revision
            now = existing["updated_at"]
            reassessment = {"state": "not-needed", "assessments": []}

        response = {
            "schemaVersion": 1, "networkId": network_id, "deviceId": device_id,
            "changed": changed, "eventId": event_id, "rosterState": target,
            "revision": device_revision, "networkRosterRevision": network_revision,
            "updatedAt": now, "reason": reason if changed else existing["reason"],
            "reassessment": reassessment,
        }
        connection.execute(
            """INSERT INTO roster_mutation_receipts
               (network_id, request_id, device_id, request_digest, event_id, result_revision,
                response_json, committed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (network_id, request_id, device_id, request_digest, event_id, device_revision,
             json.dumps(response, sort_keys=True, separators=(",", ":")), now),
        )
        connection.commit()
        return response, changed
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def add_expected_devices_from_label_map(
    store: SQLiteHealthStore,
    *,
    network_id: str,
    devices: Sequence[tuple[str, str | None]],
    skipped: int = 0,
) -> RosterImportResult:
    network_id = _validate_network_id(network_id)
    prepared: list[tuple[str, str | None, bool, str | None]] = []
    seen: set[str] = set()
    for device_id, label in devices:
        try:
            canonical_id = _validate_device_id(device_id)
            normalized_label = _normalize_label(label, supplied=label is not None)
        except ValueError:
            skipped += 1
            continue
        if canonical_id in seen:
            skipped += 1
            continue
        seen.add(canonical_id)
        prepared.append((canonical_id, normalized_label, label is not None, "expected"))

    results = _apply_changes(
        store,
        network_id=network_id,
        changes=tuple(prepared),
        origin="import",
        actor="label-map-import",
        insert_only=True,
        evidence_basis="label-map-import",
    )
    imported = sum(result.changed for result in results)
    return RosterImportResult(
        network_id=network_id,
        imported=imported,
        already_present=len(results) - imported,
        skipped=skipped,
    )


def _apply_changes(
    store: SQLiteHealthStore,
    *,
    network_id: str,
    changes: Sequence[tuple[str, str | None, bool, str | None]],
    origin: str,
    actor: str,
    insert_only: bool,
    evidence_basis: str | None = None,
) -> list[RosterDeviceMutation]:
    connection = store._connect()
    results: list[RosterDeviceMutation] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        for device_id, requested_label, label_supplied, requested_state in changes:
            existing = connection.execute(
                """SELECT label, roster_state, revision, updated_at, expected_since
                   FROM expected_devices WHERE network_id=? AND device_id=?""",
                (network_id, device_id),
            ).fetchone()
            if existing is not None and insert_only:
                revision = connection.execute(
                    "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                    (network_id,),
                ).fetchone()
                results.append(RosterDeviceMutation(
                    network_id, device_id, False, existing["roster_state"],
                    existing["label"], existing["revision"],
                    int(revision["revision"]) if revision else 0,
                    existing["updated_at"], existing["expected_since"], None,
                ))
                continue

            now = datetime.now(timezone.utc).isoformat()
            previous_state = existing["roster_state"] if existing else None
            previous_label = existing["label"] if existing else None
            previous_epoch = existing["expected_since"] if existing else None
            next_state = (
                requested_state if requested_state is not None
                else previous_state or "expected"
            )
            next_label = requested_label if label_supplied else previous_label
            if existing is None:
                next_epoch = now if next_state == "expected" else None
            elif next_state == "expected" and previous_state != "expected":
                next_epoch = now
            elif next_state == "expected":
                next_epoch = previous_epoch
            else:
                next_epoch = None

            changed = (
                existing is None
                or next_state != previous_state
                or next_label != previous_label
            )
            if not changed:
                revision_row = connection.execute(
                    "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                    (network_id,),
                ).fetchone()
                results.append(RosterDeviceMutation(
                    network_id, device_id, False, next_state, next_label,
                    existing["revision"], int(revision_row["revision"]) if revision_row else 0,
                    existing["updated_at"], previous_epoch, None,
                ))
                continue

            device_revision = (int(existing["revision"]) if existing else 0) + 1
            revision_row = connection.execute(
                "SELECT revision FROM network_roster_revisions WHERE network_id=?",
                (network_id,),
            ).fetchone()
            network_revision = (int(revision_row["revision"]) if revision_row else 0) + 1
            connection.execute(
                """INSERT INTO network_roster_revisions(network_id, revision, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(network_id) DO UPDATE SET
                       revision=excluded.revision, updated_at=excluded.updated_at""",
                (network_id, network_revision, now),
            )
            connection.execute(
                """INSERT INTO expected_devices
                   (network_id, device_id, label, roster_state, updated_at, revision,
                    reason, expected_since, change_source)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                   ON CONFLICT(network_id, device_id) DO UPDATE SET
                       label=excluded.label, roster_state=excluded.roster_state,
                       updated_at=excluded.updated_at, revision=excluded.revision,
                       reason=excluded.reason, expected_since=excluded.expected_since,
                       change_source=excluded.change_source""",
                (network_id, device_id, next_label, next_state, now, device_revision,
                 next_epoch, origin),
            )
            event_id = f"roster-event:{uuid.uuid4()}"
            if existing is None:
                action = "enroll"
            elif next_state != previous_state and next_label != previous_label:
                action = "update"
            elif next_state != previous_state:
                action = "set-state"
            else:
                action = "set-label"
            connection.execute(
                """INSERT INTO roster_lifecycle_events
                   (event_id, network_id, device_id, action, from_state, to_state,
                    previous_label, new_label, previous_expected_since,
                    new_expected_since, occurred_at, origin, actor, evidence_basis,
                    device_revision, network_revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, network_id, device_id, action, previous_state, next_state,
                 previous_label, next_label, previous_epoch, next_epoch, now,
                 origin, actor, evidence_basis or ("manual-cli" if origin == "cli" else None),
                 device_revision, network_revision),
            )
            results.append(RosterDeviceMutation(
                network_id, device_id, True, next_state, next_label,
                device_revision, network_revision, now, next_epoch, event_id,
            ))
        if any(result.changed for result in results):
            revisions = tuple(store._reassess_network(connection, network_id))
            results = [
                replace(result, reassessment=revisions) if result.changed else result
                for result in results
            ]
        connection.commit()
        return results
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
