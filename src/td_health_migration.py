"""Read-only health-history eligibility inventory and replay adapters."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from td_health_comparison import (
    COMPARISON_INTERVALS,
    ROUTE64_SAMPLE_CONTRACT_VERSION,
    ComparisonPolicy,
    comparison_id,
    resolve_interval_candidate,
)
from td_health_evaluator import (
    EVALUATOR_VERSION,
    evaluate_observation,
    evaluation_inputs_from_payload,
)
from td_health_manifest import HealthProfile, load_health_manifest
from td_health_observation_model import (
    EvaluationInputDomain,
    EvaluationInputState,
    EvaluationInputs,
    HistoryMigrationEligibility,
    HistoryMigrationInventory,
    HistoryMigrationInventoryItem,
    device_id_from_ext_address,
)
from td_health_observation_store import HOBAT_DATABASE_FILENAME, HealthStoreError
from td_health_policy import HealthPolicy
from td_health_sqlite import SQLiteHealthStore


_SUPPORTED_EVALUATORS = frozenset({"snapshot-v10", "snapshot-v11", EVALUATOR_VERSION})
_DEVICE_ID_PREFIX = "extaddr:"


class HealthMigrationInventoryError(HealthStoreError):
    """Raised when a history inventory cannot be read without mutation."""


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    ).hexdigest()


def _device_id(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(_DEVICE_ID_PREFIX):
        raise ValueError("invalid-device-id")
    return device_id_from_ext_address(value.removeprefix(_DEVICE_ID_PREFIX))


def _available_roster_gaps(
    connection: sqlite3.Connection,
    *,
    network_id: str,
    observed_device_ids: frozenset[str],
    expected_device_ids: frozenset[str],
) -> tuple[str, ...]:
    current_expected = {
        row["device_id"]
        for row in connection.execute(
            "SELECT device_id FROM expected_devices WHERE network_id=?",
            (network_id,),
        )
    }
    retained_device_ids = {
        row["device_id"]
        for row in connection.execute(
            """SELECT DISTINCT retained.device_id
               FROM (
                   SELECT ds.device_id
                   FROM device_samples ds
                   JOIN observations o USING (observation_id)
                   WHERE o.network_id=?
                   UNION
                   SELECT r.from_device_id AS device_id
                   FROM relationship_samples rs
                   JOIN observations o USING (observation_id)
                   JOIN relationships r USING (relationship_id)
                   WHERE o.network_id=?
                   UNION
                   SELECT r.to_device_id AS device_id
                   FROM relationship_samples rs
                   JOIN observations o USING (observation_id)
                   JOIN relationships r USING (relationship_id)
                   WHERE o.network_id=?
               ) AS retained""",
            (network_id, network_id, network_id),
        )
    }
    unverifiable = (
        expected_device_ids
        - observed_device_ids
        - current_expected
        - retained_device_ids
    )
    return ("historical-roster-reference-unverifiable",) if unverifiable else ()


def _unavailable_inputs(
    profile: HealthProfile, reason: str
) -> EvaluationInputs:
    unavailable = EvaluationInputDomain(
        EvaluationInputState.UNAVAILABLE, (reason,)
    )
    not_applicable = EvaluationInputDomain(
        EvaluationInputState.NOT_APPLICABLE
    )
    routing_applicable = (
        profile.border_router_authority
        and profile.coverage["externalRouting"] != "missing"
    )
    return EvaluationInputs(
        roster=unavailable,
        expected_device_ids=None,
        absence_history=unavailable,
        prior_complete_absences=None,
        duplicate_relationships=unavailable,
        duplicate_relationship_ids=None,
        omr_prefix=unavailable if routing_applicable else not_applicable,
        omr_prefix_value=None,
        omr_source=None,
        device_ipv6_addresses=unavailable if routing_applicable else not_applicable,
        device_ipv6_address_values=None,
        observed_device_ipv6_address_values={},
        roster_context=None,
        history_boundary=None,
    )


def _saved_context_inputs(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    observation,
    profile: HealthProfile,
) -> tuple[EvaluationInputs, tuple[str, ...]]:
    try:
        raw = json.loads(row["reproduction_context_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid-reproduction-context") from exc
    if raw == {}:
        return _unavailable_inputs(profile, "input-not-retained"), (
            "evaluation-context-unavailable",
        )
    if not isinstance(raw, dict):
        raise ValueError("invalid-reproduction-context")
    policy_data = raw.get("healthPolicy")
    profile_data = raw.get("healthProfile")
    if not isinstance(policy_data, dict) or not isinstance(profile_data, dict):
        raise ValueError("invalid-policy-or-profile-context")
    if raw.get("evaluatorVersion") != row["evaluator_version"]:
        raise ValueError("reproduction-evaluator-mismatch")
    if profile_data.get("profileId") != row["profile_id"]:
        raise ValueError("reproduction-profile-mismatch")
    if row["profile_id"] != profile.profile_id:
        raise LookupError("unsupported-profile")
    expected_sample_contract = (
        ROUTE64_SAMPLE_CONTRACT_VERSION
        if row["dataset_id"] == "otbr_cli_networkdiag_fetch_all"
        else "comparison-v1"
    )
    if row["sample_contract_version"] != expected_sample_contract:
        raise LookupError("unsupported-sample-contract")

    if raw.get("schemaVersion") == 2:
        if (
            policy_data.get("digest") != row["health_policy_digest"]
            or raw.get("networkRosterRevision") != row["network_roster_revision"]
        ):
            raise ValueError("reproduction-input-identity-mismatch")
        inputs = evaluation_inputs_from_payload(raw.get("evaluationInputs"))
        presence = raw.get("presenceInputs")
        if not isinstance(presence, dict):
            raise ValueError("invalid-presence-context")
        if presence.get("sampleContractVersion") != row["sample_contract_version"]:
            raise ValueError("sample-contract-context-mismatch")
        if presence.get("observedDeviceIds") != sorted(
            device.device_id for device in observation.devices
        ):
            raise ValueError("observed-presence-context-mismatch")
        if presence.get("complete") is not (
            observation.completeness.value == "complete"
        ):
            raise ValueError("completeness-context-mismatch")
        roster_presence = presence.get("roster")
        absence_presence = presence.get("absenceHistory")
        absence_inputs = raw.get("priorCompleteAbsences")
        expected_inputs = raw.get("expectedDeviceIds")
        roster_context = raw.get("rosterContext")
        input_payload = raw.get("evaluationInputs")
        if (
            not isinstance(input_payload, dict)
            or not isinstance(absence_presence, dict)
            or not isinstance(absence_inputs, dict)
            or not isinstance(expected_inputs, list)
            or not isinstance(roster_context, dict)
        ):
            raise ValueError("invalid-evaluation-input-identity")
        absence_domain = input_payload.get("domains", {}).get("absenceHistory")
        roster_domain = input_payload.get("domains", {}).get("roster")
        if not isinstance(absence_domain, dict) or not isinstance(roster_domain, dict):
            raise ValueError("invalid-evaluation-input-domains")
        if (
            not isinstance(roster_presence, dict)
            or roster_presence.get("expectedDeviceIds")
            != sorted(inputs.expected_device_ids or ())
            or roster_presence.get("state") != inputs.roster.state.value
            or roster_presence.get("reasonCodes")
            != list(inputs.roster.reason_codes)
            or absence_presence.get("state")
            != inputs.absence_history.state.value
            or absence_presence.get("reasonCodes")
            != list(inputs.absence_history.reason_codes)
            or absence_presence.get("priorCompleteAbsences")
            != dict(sorted((inputs.prior_complete_absences or {}).items()))
            or absence_inputs
            != dict(sorted((inputs.prior_complete_absences or {}).items()))
            or expected_inputs != sorted(inputs.expected_device_ids or ())
            or raw.get("rosterContext") != inputs.roster_context
            or raw.get("historyBoundary") != inputs.history_boundary
            or absence_domain.get("state") != inputs.absence_history.state.value
            or absence_domain.get("reasonCodes")
            != list(inputs.absence_history.reason_codes)
            or roster_domain.get("state") != inputs.roster.state.value
            or roster_domain.get("reasonCodes") != list(inputs.roster.reason_codes)
            or input_payload.get("absenceHistory", {}).get("historyBoundary")
            != inputs.history_boundary
        ):
            raise ValueError("evaluation-context-contradiction")

        policy_identity = {
            "version": policy_data.get("version"),
            "digest": policy_data.get("digest"),
            "offlineConsecutiveCompleteObservations": policy_data.get(
                "offlineConsecutiveCompleteObservations"
            ),
            "offlinePoorDeviceRatioThreshold": policy_data.get(
                "offlinePoorDeviceRatioThreshold"
            ),
            "thresholds": policy_data.get("thresholds"),
        }
        profile_identity = {
            "profileId": profile_data.get("profileId"),
            "identityFile": profile_data.get("identityFile"),
            "requiredOutcomes": profile_data.get("requiredOutcomes"),
            "coverage": profile_data.get("coverage"),
            "topologyAuthority": profile_data.get("topologyAuthority"),
            "borderRouterAuthority": profile_data.get("borderRouterAuthority"),
        }
        assessment_identity = {
            "evaluatorVersion": raw.get("evaluatorVersion"),
            "healthPolicy": policy_identity,
            "healthProfile": profile_identity,
            "sampleContractVersion": row["sample_contract_version"],
            "evaluationInputs": input_payload,
        }
        roster_identity = {
            "state": inputs.roster.state.value,
            "reasonCodes": list(inputs.roster.reason_codes),
            "context": inputs.roster_context or {},
        }
        if (
            _digest(assessment_identity) != row["policy_digest"]
            or _digest(presence) != row["presence_input_digest"]
            or _digest(roster_identity) != row["roster_context_digest"]
        ):
            raise ValueError("evaluation-context-digest-mismatch")
        return _validate_roster_references(connection, row, observation, inputs)

    if raw.get("schemaVersion") != 1:
        raise ValueError("unsupported-reproduction-context")
    if row["evaluator_version"] not in {"snapshot-v10", "snapshot-v11"}:
        raise LookupError("unsupported-context-version")
    if policy_data.get("digest") != row["health_policy_digest"]:
        raise ValueError("historical-policy-digest-mismatch")
    if raw.get("networkRosterRevision") != row["network_roster_revision"]:
        raise ValueError("roster-revision-mismatch")
    policy_data = raw.get("healthPolicy")
    profile_data = raw.get("healthProfile")
    if not isinstance(policy_data, dict) or not isinstance(profile_data, dict):
        raise ValueError("invalid-policy-or-profile-context")
    if (
        not isinstance(policy_data.get("version"), str)
        or not isinstance(policy_data.get("digest"), str)
        or type(policy_data.get("offlineConsecutiveCompleteObservations")) is not int
        or policy_data["offlineConsecutiveCompleteObservations"] < 2
        or not isinstance(policy_data.get("thresholds"), dict)
        or not isinstance(profile_data.get("coverage"), dict)
    ):
        raise ValueError("invalid-policy-or-profile-context")
    ratio = policy_data.get("offlinePoorDeviceRatioThreshold")
    if (
        not isinstance(ratio, (int, float))
        or isinstance(ratio, bool)
        or not math.isfinite(float(ratio))
        or not 0 <= ratio <= 1
        or any(
            not isinstance(metric, str)
            or not isinstance(bands, dict)
            or not bands
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in bands.values()
            )
            for metric, bands in policy_data["thresholds"].items()
        )
    ):
        raise ValueError("invalid-policy-or-profile-context")
    saved_profile = profile_data
    if (
        saved_profile.get("profileId") != profile.profile_id
        or saved_profile.get("identityFile") != profile.identity_file
        or saved_profile.get("requiredOutcomes") != list(profile.required_outcomes)
        or saved_profile.get("coverage") != dict(profile.coverage)
        or saved_profile.get("topologyAuthority") is not profile.topology_authority
        or saved_profile.get("borderRouterAuthority") is not profile.border_router_authority
    ):
        raise LookupError("unsupported-profile")

    expected_raw = raw.get("expectedDeviceIds")
    absence_raw = raw.get("priorCompleteAbsences")
    roster = raw.get("rosterContext")
    presence = raw.get("presenceInputs")
    if (
        not isinstance(expected_raw, list)
        or not isinstance(absence_raw, dict)
        or not isinstance(roster, dict)
        or not isinstance(presence, dict)
        or roster.get("schemaVersion") != 1
        or roster.get("networkId") != row["network_id"]
        or roster.get("networkRosterRevision") != row["network_roster_revision"]
    ):
        raise ValueError("invalid-roster-context")
    normalized_expected = tuple(_device_id(value) for value in expected_raw)
    if normalized_expected != tuple(sorted(set(normalized_expected))):
        raise ValueError("invalid-expected-device-ids")
    expected_ids = frozenset(normalized_expected)
    observed_ids = frozenset(device.device_id for device in observation.devices)
    if (
        presence.get("expectedDeviceIds") != sorted(expected_ids)
        or presence.get("observedDeviceIds") != sorted(observed_ids)
        or presence.get("sampleContractVersion") != row["sample_contract_version"]
        or presence.get("complete") is not (
            observation.completeness.value == "complete"
        )
        or raw.get("presenceInputs", {}).get("priorCompleteAbsences", {})
        != dict(sorted(absence_raw.items()))
    ):
        raise ValueError("presence-context-mismatch")
    if not all(
        _device_id(key) in expected_ids
        and type(count) is int
        and count >= 0
        for key, count in absence_raw.items()
    ):
        raise ValueError("invalid-absence-history")
    records = roster.get("records")
    if not isinstance(records, list):
        raise ValueError("invalid-roster-records")
    normalized_records: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid-roster-record")
        device_id = _device_id(record.get("deviceId"))
        if (
            device_id in record_ids
            or record.get("rosterState")
            not in {"expected", "retired", "intentionally-offline", "intermittent"}
            or type(record.get("revision")) is not int
            or record["revision"] < 0
        ):
            raise ValueError("invalid-roster-record")
        record_ids.add(device_id)
        expected_since = record.get("expectedSince")
        if expected_since is not None:
            SQLiteHealthStore._utc_instant(expected_since)
        normalized_records.append(dict(record, deviceId=device_id))
    if not expected_ids <= record_ids:
        raise ValueError("expected-roster-context-mismatch")
    if any(
        record.get("rosterState") != "expected"
        for record in normalized_records
        if record["deviceId"] in expected_ids
    ):
        raise ValueError("expected-roster-context-mismatch")
    if expected_ids - observed_ids:
        gaps = _available_roster_gaps(
            connection,
            network_id=row["network_id"],
            observed_device_ids=observed_ids,
            expected_device_ids=expected_ids,
        )
        if gaps:
            unavailable = _unavailable_inputs(profile, gaps[0])
            return unavailable, gaps

    duplicate_domain = EvaluationInputDomain(
        EvaluationInputState.UNAVAILABLE, ("input-not-retained",)
    )
    routing_applicable = (
        profile.border_router_authority
        and profile.coverage["externalRouting"] != "missing"
    )
    unavailable = EvaluationInputDomain(
        EvaluationInputState.UNAVAILABLE, ("input-not-retained",)
    )
    not_applicable = EvaluationInputDomain(EvaluationInputState.NOT_APPLICABLE)
    roster_context = dict(roster, records=normalized_records)
    return EvaluationInputs(
        roster=EvaluationInputDomain(EvaluationInputState.AVAILABLE),
        expected_device_ids=expected_ids,
        absence_history=EvaluationInputDomain(EvaluationInputState.AVAILABLE),
        prior_complete_absences=dict(absence_raw),
        duplicate_relationships=duplicate_domain,
        duplicate_relationship_ids=None,
        omr_prefix=unavailable if routing_applicable else not_applicable,
        omr_prefix_value=None,
        omr_source=None,
        device_ipv6_addresses=unavailable if routing_applicable else not_applicable,
        device_ipv6_address_values=None,
        observed_device_ipv6_address_values={},
        roster_context=roster_context,
        history_boundary=raw.get("historyBoundary"),
    ), ("historical-input-gaps",)


def _validate_roster_references(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    observation,
    inputs: EvaluationInputs,
) -> tuple[EvaluationInputs, tuple[str, ...]]:
    if inputs.roster.state is not EvaluationInputState.AVAILABLE:
        return inputs, tuple(inputs.roster.reason_codes)
    gaps = _available_roster_gaps(
        connection,
        network_id=row["network_id"],
        observed_device_ids=frozenset(
            device.device_id for device in observation.devices
        ),
        expected_device_ids=inputs.expected_device_ids or frozenset(),
    )
    if not gaps:
        return inputs, ()
    unavailable_domain = EvaluationInputDomain(
        EvaluationInputState.UNAVAILABLE, gaps
    )
    return replace(
        inputs,
        roster=unavailable_domain,
        expected_device_ids=None,
        absence_history=unavailable_domain,
        prior_complete_absences=None,
        roster_context=None,
    ), gaps


def _stored_findings(connection: sqlite3.Connection, assessment_id: str) -> tuple:
    return tuple(
        (
            row["finding_id"], row["rule_id"], row["status"], row["scope"],
            row["rank"], row["title"], row["summary"], row["why_it_matters"],
            row["device_ids_json"], row["relationship_ids_json"],
            row["evidence_json"], row["confidence"], row["action"],
            row["verify"], row["source_files_json"],
        )
        for row in connection.execute(
            "SELECT * FROM findings WHERE assessment_id=? ORDER BY rank DESC, finding_id",
            (assessment_id,),
        )
    )


def _generated_findings(assessment) -> tuple:
    return tuple(
        (
            finding.finding_id, finding.rule_id, finding.status.value,
            finding.scope.value, int(finding.rank), finding.title, finding.summary,
            finding.why_it_matters,
            json.dumps(finding.device_ids), json.dumps(finding.relationship_ids),
            json.dumps(finding.evidence, sort_keys=True), finding.confidence.value,
            finding.action, finding.verify, json.dumps(finding.source_files),
        )
        for finding in sorted(
            assessment.findings, key=lambda item: (-int(item.rank), item.finding_id)
        )
    )


def inventory_health_history(
    store: SQLiteHealthStore,
    *,
    target_policy: HealthPolicy,
    dataset_ids: tuple[str, ...] | None = None,
    network_id: str | None = None,
) -> HistoryMigrationInventory:
    """Classify one preferred retained assessment per observation without writes."""
    if not store.read_only:
        raise HealthMigrationInventoryError(
            "Health-history inventory requires a read-only store"
        )
    if not store.path.exists():
        return HistoryMigrationInventory(0, "", _digest([]), ())

    manifest = load_health_manifest()
    unknown = set(dataset_ids or ()) - set(manifest.datasets)
    if unknown:
        raise HealthMigrationInventoryError(
            f"Dataset is not health eligible: {sorted(unknown)[0]}"
        )
    where = []
    parameters: list[str] = []
    if dataset_ids:
        where.append(f"o.dataset_id IN ({','.join('?' for _ in dataset_ids)})")
        parameters.extend(dataset_ids)
    if network_id is not None:
        where.append("o.network_id=?")
        parameters.append(network_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    target_contract_digest = _digest(
        {
            "evaluatorVersion": EVALUATOR_VERSION,
            "policyVersion": target_policy.version,
            "policyDigest": target_policy.digest,
            "manifestSchema": manifest.schema_version,
            "datasets": {
                dataset_id: {
                    "profileId": manifest.dataset(dataset_id).health_profile.profile_id,
                    "sampleContract": (
                        ROUTE64_SAMPLE_CONTRACT_VERSION
                        if dataset_id == "otbr_cli_networkdiag_fetch_all"
                        else "comparison-v1"
                    ),
                }
                for dataset_id in sorted(manifest.datasets)
            },
        }
    )
    with closing(store._connect()) as connection:
        connection.execute("BEGIN")
        schema_table = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='schema_migrations'"""
        ).fetchone()
        if schema_table is None:
            raise HealthMigrationInventoryError(
                "Health-history database has no supported schema"
            )
        schema_row = connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()
        schema_version = int(schema_row["version"] or 0)
        if schema_version not in {7, 8}:
            raise HealthMigrationInventoryError(
                f"Health-history migration supports database schemas 7 and 8, not {schema_version}"
            )
        rows = connection.execute(
            f"""SELECT a.*, o.datasource_id, o.dataset_id, o.network_id,
                       o.network_name, o.observed_at, o.ingested_at, o.completeness,
                       o.source_set_digest
                FROM assessments a JOIN observations o USING (observation_id)
                {clause}
                ORDER BY o.observation_id""",
            parameters,
        ).fetchall()
        by_observation: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_observation.setdefault(row["observation_id"], []).append(row)
        preferences: dict[str, sqlite3.Row] = {}
        if schema_version >= 8:
            preferences = {
                row["observation_id"]: row
                for row in connection.execute(
                    """SELECT observation_id, assessment_id,
                              selection_basis_assessment_id, origin, migration_id
                       FROM health_assessment_preferences"""
                )
            }
        items: list[HistoryMigrationInventoryItem] = []
        inventory_rows: list[dict[str, str]] = []
        for observation_id, assessment_rows in by_observation.items():
            preference = preferences.get(observation_id)
            if schema_version < 8:
                source = max(
                    assessment_rows,
                    key=lambda item: (
                        item["network_roster_revision"],
                        SQLiteHealthStore._utc_instant(item["assessed_at"]),
                        item["assessment_id"],
                    ),
                )
                classification = HistoryMigrationEligibility.REPLAYABLE
                reasons = ()
            elif preference is None:
                source = assessment_rows[0]
                classification = HistoryMigrationEligibility.INVALID
                reasons = ("missing-schema-8-assessment-preference",)
            else:
                source_id = preference["selection_basis_assessment_id"]
                source = next(
                    (
                        item for item in assessment_rows
                        if item["assessment_id"] == source_id
                    ),
                    None,
                )
                if source is None:
                    source = max(
                        assessment_rows,
                        key=lambda item: (
                            item["network_roster_revision"],
                            SQLiteHealthStore._utc_instant(item["assessed_at"]),
                            item["assessment_id"],
                        ),
                    )
                    classification = HistoryMigrationEligibility.INVALID
                    reasons = ("invalid-native-selection-basis",)
                else:
                    classification = HistoryMigrationEligibility.REPLAYABLE
                    reasons = ()
                    selected = next(
                        (
                            item for item in assessment_rows
                            if item["assessment_id"] == preference["assessment_id"]
                        ),
                        None,
                    )
                    lineage_valid = (
                        selected is not None
                        and (
                            preference["origin"] == "native"
                            and preference["migration_id"] is None
                            and preference["assessment_id"] == source_id
                            or preference["origin"] == "migration"
                            and preference["migration_id"] is not None
                            and connection.execute(
                                """SELECT 1 FROM health_assessment_upgrades
                                   WHERE source_assessment_id=?
                                     AND target_assessment_id=?
                                     AND migration_id=?""",
                                (
                                    source_id,
                                    preference["assessment_id"],
                                    preference["migration_id"],
                                ),
                            ).fetchone() is not None
                        )
                    )
                    if not lineage_valid:
                        classification = HistoryMigrationEligibility.INVALID
                        reasons = ("invalid-assessment-preference-lineage",)
            dataset = manifest.datasets.get(source["dataset_id"])
            replay = None
            inputs = None
            try:
                if classification is HistoryMigrationEligibility.INVALID:
                    raise ValueError(reasons[0])
                if dataset is None or source["datasource_id"] != dataset.datasource_id:
                    raise LookupError("unsupported-dataset")
                if source["evaluator_version"] not in _SUPPORTED_EVALUATORS:
                    raise LookupError("unsupported-evaluator")
                if source["profile_id"] != dataset.health_profile.profile_id:
                    raise LookupError("unsupported-profile")
                expected_contract = (
                    ROUTE64_SAMPLE_CONTRACT_VERSION
                    if source["dataset_id"] == "otbr_cli_networkdiag_fetch_all"
                    else "comparison-v1"
                )
                if source["sample_contract_version"] != expected_contract:
                    raise LookupError("unsupported-sample-contract")
                observation = SQLiteHealthStore._retained_observation(
                    connection, source
                )
                inputs, reasons = _saved_context_inputs(
                    connection,
                    row=source,
                    observation=observation,
                    profile=dataset.health_profile,
                )
                replay = evaluate_observation(
                    observation,
                    target_policy,
                    profile=dataset.health_profile,
                    evaluation_inputs=inputs,
                    sample_contract_version=source["sample_contract_version"],
                    network_roster_revision=source["network_roster_revision"],
                    assessed_at=source["assessed_at"],
                )
                if inputs.evaluation_context_complete and inputs.verdict_context_complete:
                    classification = HistoryMigrationEligibility.REPLAYABLE
                else:
                    classification = HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS
                if (
                    source["evaluator_version"] == EVALUATOR_VERSION
                    and source["health_policy_digest"] == target_policy.digest
                    and replay.assessment_id == source["assessment_id"]
                    and replay.status.value == source["status"]
                    and replay.confidence.value == source["confidence"]
                    and json.loads(source["coverage_json"]) == replay.coverage
                    and _stored_findings(connection, source["assessment_id"])
                    == _generated_findings(replay)
                ):
                    classification = HistoryMigrationEligibility.ALREADY_CURRENT
                    reasons = ()
                existing_upgrade = connection.execute(
                    """SELECT u.target_assessment_id, u.migration_id,
                              u.replay_input_digest, u.unavailable_domains_json
                       FROM health_assessment_upgrades u
                       WHERE u.source_assessment_id=?
                         AND u.target_contract_digest=?""",
                    (source["assessment_id"], target_contract_digest),
                ).fetchone() if schema_version >= 8 else None
                if existing_upgrade is not None:
                    target = connection.execute(
                        "SELECT * FROM assessments WHERE assessment_id=?",
                        (existing_upgrade["target_assessment_id"],),
                    ).fetchone()
                    if (
                        existing_upgrade["target_assessment_id"]
                        != replay.assessment_id
                        or target is None
                        or target["observation_id"] != source["observation_id"]
                        or target["evaluator_version"] != replay.evaluator_version
                        or target["policy_digest"] != replay.policy_digest
                        or target["status"] != replay.status.value
                        or target["confidence"] != replay.confidence.value
                        or json.loads(target["coverage_json"]) != replay.coverage
                        or _stored_findings(
                            connection, existing_upgrade["target_assessment_id"]
                        ) != _generated_findings(replay)
                    ):
                        raise ValueError("existing-upgrade-target-conflict")
                    classification = HistoryMigrationEligibility.ALREADY_CURRENT
                    reasons = ()
            except LookupError as exc:
                classification = HistoryMigrationEligibility.UNSUPPORTED
                reasons = (str(exc),)
            except (ValueError, TypeError, sqlite3.DatabaseError, KeyError) as exc:
                classification = HistoryMigrationEligibility.INVALID
                reasons = (str(exc) or "invalid-retained-evidence",)
            item = HistoryMigrationInventoryItem(
                source["network_id"],
                source["dataset_id"],
                source["observation_id"],
                source["assessment_id"],
                classification,
                reasons,
                source["evaluator_version"],
                source["health_policy_digest"],
                source["sample_contract_version"],
                (
                    preference["assessment_id"]
                    if preference is not None
                    else source["assessment_id"]
                ),
                (
                    replay.assessment_id
                    if replay is not None
                    else None
                ),
                tuple(
                    name
                    for name, domain in inputs.domains().items()
                    if domain.state is EvaluationInputState.UNAVAILABLE
                ) if inputs is not None else (),
                source["status"],
                replay.status.value if replay is not None else None,
                len(_stored_findings(connection, source["assessment_id"])),
                len(replay.findings) if replay is not None else None,
                json.loads(source["coverage_json"]),
                replay.coverage if replay is not None else None,
                replay.policy_digest if replay is not None else None,
            )
            items.append(item)
            inventory_rows.append(
                {
                    "observationId": item.observation_id,
                    "assessmentId": item.source_assessment_id,
                    "datasetId": item.dataset_id,
                    "networkId": item.network_id,
                    "sampleContract": item.sample_contract_version,
                    "inputDigest": source["policy_digest"],
                    "rosterContextDigest": source["roster_context_digest"],
                    "presenceInputDigest": source["presence_input_digest"],
                }
            )
        connection.rollback()
    return HistoryMigrationInventory(
        schema_version,
        target_contract_digest,
        _digest(inventory_rows),
        tuple(items),
        tuple(sorted(dataset_ids or manifest.datasets)),
        network_id,
    )


def _assessment_row(
    connection: sqlite3.Connection, assessment_id: str
) -> sqlite3.Row:
    row = connection.execute(
        """SELECT a.*, o.datasource_id, o.dataset_id, o.network_id,
                  o.network_name, o.observed_at, o.ingested_at, o.completeness,
                  o.source_set_digest
           FROM assessments a JOIN observations o USING (observation_id)
           WHERE a.assessment_id=?""",
        (assessment_id,),
    ).fetchone()
    if row is None:
        raise sqlite3.DatabaseError("Migration source assessment is no longer retained")
    return row


def _replay_item(
    connection: sqlite3.Connection,
    item: HistoryMigrationInventoryItem,
    target_policy: HealthPolicy,
):
    row = _assessment_row(connection, item.source_assessment_id)
    manifest = load_health_manifest()
    dataset = manifest.dataset(item.dataset_id)
    observation = SQLiteHealthStore._retained_observation(connection, row)
    inputs, _ = _saved_context_inputs(
        connection,
        row=row,
        observation=observation,
        profile=dataset.health_profile,
    )
    assessment = evaluate_observation(
        observation,
        target_policy,
        profile=dataset.health_profile,
        evaluation_inputs=inputs,
        sample_contract_version=row["sample_contract_version"],
        network_roster_revision=row["network_roster_revision"],
        assessed_at=row["assessed_at"],
    )
    if (
        item.target_assessment_id is not None
        and assessment.assessment_id != item.target_assessment_id
        or item.replay_input_digest is not None
        and assessment.policy_digest != item.replay_input_digest
    ):
        raise sqlite3.DatabaseError(
            "Locked replay no longer matches its confirmed inventory preview"
        )
    return row, observation, inputs, assessment


def _assessment_matches(
    connection: sqlite3.Connection, assessment
) -> bool:
    row = connection.execute(
        "SELECT * FROM assessments WHERE assessment_id=?",
        (assessment.assessment_id,),
    ).fetchone()
    if row is None:
        return False
    return (
        row["observation_id"] == assessment.observation_id
        and row["policy_version"] == assessment.policy_version
        and row["policy_digest"] == assessment.policy_digest
        and row["evaluator_version"] == assessment.evaluator_version
        and row["profile_id"] == assessment.profile_id
        and row["status"] == assessment.status.value
        and row["confidence"] == assessment.confidence.value
        and json.loads(row["coverage_json"]) == assessment.coverage
        and row["assessed_at"] == assessment.assessed_at
        and row["sample_contract_version"] == assessment.sample_contract_version
        and row["health_policy_digest"] == assessment.health_policy_digest
        and row["roster_context_digest"] == assessment.roster_context_digest
        and row["presence_input_digest"] == assessment.presence_input_digest
        and row["network_roster_revision"] == assessment.network_roster_revision
        and json.loads(row["reproduction_context_json"])
        == assessment.reproduction_context
        and _stored_findings(connection, assessment.assessment_id)
        == _generated_findings(assessment)
    )


def _report_item(item: HistoryMigrationInventoryItem) -> dict[str, Any]:
    return {
        "networkId": item.network_id,
        "datasetId": item.dataset_id,
        "observationId": item.observation_id,
        "sourceAssessmentId": item.source_assessment_id,
        "preferredAssessmentId": item.preferred_assessment_id,
        "targetAssessmentId": item.target_assessment_id,
        "eligibility": item.eligibility.value,
        "reasons": list(item.reason_codes),
        "unavailableDomains": list(item.unavailable_domains),
        "before": {
            "status": item.before_status,
            "findingCount": item.before_finding_count,
            "coverage": item.before_coverage,
        },
        "after": {
            "status": item.after_status,
            "findingCount": item.after_finding_count,
            "coverage": item.after_coverage,
        },
        "replayInputDigest": item.replay_input_digest,
    }


def history_migration_report(
    inventory: HistoryMigrationInventory,
    *,
    dry_run: bool,
    target_policy: HealthPolicy,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    items = [_report_item(item) for item in inventory.items]
    counts = {
        "observationsScanned": len(items),
        "alreadyCurrent": sum(
            item.eligibility is HistoryMigrationEligibility.ALREADY_CURRENT
            for item in inventory.items
        ),
        "replayable": sum(
            item.eligibility is HistoryMigrationEligibility.REPLAYABLE
            for item in inventory.items
        ),
        "replayableWithGaps": sum(
            item.eligibility is HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS
            for item in inventory.items
        ),
        "created": 0,
        "reused": 0,
        "unsupported": sum(
            item.eligibility is HistoryMigrationEligibility.UNSUPPORTED
            for item in inventory.items
        ),
        "failed": sum(
            item.eligibility is HistoryMigrationEligibility.INVALID
            for item in inventory.items
        ),
        "comparisonsStored": 0,
        "comparisonsDeferred": 0,
        "preferencesChanged": sum(
            item.target_assessment_id is not None
            and item.target_assessment_id != item.preferred_assessment_id
            for item in inventory.items
        ),
    }
    unsupported = counts["unsupported"] > 0
    failed = counts["failed"] > 0
    actionable = (
        counts["replayable"]
        + counts["replayableWithGaps"]
        + counts["preferencesChanged"]
    )
    if failed:
        outcome = "partial-with-failures" if actionable else "failed"
    elif unsupported:
        outcome = "partial-with-unsupported" if actionable else "no-op-with-unsupported"
    elif actionable:
        outcome = "dry-run-ready" if dry_run else "complete"
    else:
        outcome = "already-current" if counts["alreadyCurrent"] else "empty-scope"
    manifest = load_health_manifest()
    cohort_groups: dict[tuple[str, str], list[HistoryMigrationInventoryItem]] = {}
    for item in inventory.items:
        cohort_groups.setdefault((item.network_id, item.dataset_id), []).append(item)
    cohorts = []
    for (network_id, dataset_id), cohort_items in sorted(cohort_groups.items()):
        cohort_counts = {
            "observationsScanned": len(cohort_items),
            "alreadyCurrent": sum(
                item.eligibility is HistoryMigrationEligibility.ALREADY_CURRENT
                for item in cohort_items
            ),
            "replayable": sum(
                item.eligibility is HistoryMigrationEligibility.REPLAYABLE
                for item in cohort_items
            ),
            "replayableWithGaps": sum(
                item.eligibility
                is HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS
                for item in cohort_items
            ),
            "unsupported": sum(
                item.eligibility is HistoryMigrationEligibility.UNSUPPORTED
                for item in cohort_items
            ),
            "failed": sum(
                item.eligibility is HistoryMigrationEligibility.INVALID
                for item in cohort_items
            ),
        }
        cohort_outcome = (
            "failed" if cohort_counts["failed"]
            else "partial-with-unsupported" if cohort_counts["unsupported"]
            else "dry-run-ready"
            if cohort_counts["replayable"] or cohort_counts["replayableWithGaps"]
            else "already-current"
        )
        cohort_digests = {item.policy_digest for item in cohort_items}
        native_digest = (
            next(iter(cohort_digests)) if len(cohort_digests) == 1 else None
        )
        cohorts.append(
            {
                "networkId": network_id,
                "datasetId": dataset_id,
                "outcome": cohort_outcome,
                "nativePolicyDigest": native_digest,
                "nativePolicyMatches": native_digest == target_policy.digest,
                "totals": cohort_counts,
            }
        )
    return {
        "schemaVersion": 1,
        "dryRun": dry_run,
        "outcome": outcome,
        "target": {
            "evaluatorVersion": EVALUATOR_VERSION,
            "policyVersion": target_policy.version,
            "policyDigest": target_policy.digest,
            "contractDigest": inventory.target_contract_digest,
            "profileContracts": {
                dataset_id: {
                    "profileId": manifest.dataset(dataset_id).health_profile.profile_id,
                    "sampleContractVersion": (
                        ROUTE64_SAMPLE_CONTRACT_VERSION
                        if dataset_id == "otbr_cli_networkdiag_fetch_all"
                        else "comparison-v1"
                    ),
                }
                for dataset_id in inventory.dataset_ids
            },
        },
        "sourceSchemaVersion": inventory.schema_version,
        "outputSchemaVersion": 8,
        "inventoryDigest": inventory.source_inventory_digest,
        "backupPath": str(backup_path) if backup_path else None,
        "totals": counts,
        "cohorts": cohorts,
        "items": items,
    }


class HealthMigrationError(HealthMigrationInventoryError):
    """Raised when an explicit health-history migration cannot safely proceed."""


def _comparison_reservations(
    store: SQLiteHealthStore,
    inventory: HistoryMigrationInventory,
) -> tuple[set[str], dict[tuple[str, str], frozenset[str]], dict[tuple[str, str], int]]:
    """Freeze globally prioritized migration pairs before committing cohorts."""
    excluded_cohorts = {
        (item.network_id, item.dataset_id)
        for item in inventory.items
        if item.eligibility is HistoryMigrationEligibility.INVALID
    }
    cohort_items: dict[
        tuple[str, str], list[HistoryMigrationInventoryItem]
    ] = {}
    actionable_cohorts: set[tuple[str, str]] = set()
    for item in inventory.items:
        cohort = (item.network_id, item.dataset_id)
        actionable = (
            item.eligibility
            in {
                HistoryMigrationEligibility.REPLAYABLE,
                HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS,
            }
            or (
                item.eligibility is HistoryMigrationEligibility.ALREADY_CURRENT
                and item.target_assessment_id is not None
                and item.target_assessment_id != item.preferred_assessment_id
            )
        )
        if actionable:
            actionable_cohorts.add(cohort)
    for item in inventory.items:
        cohort = (item.network_id, item.dataset_id)
        supported_endpoint = (
            item.eligibility
            in {
                HistoryMigrationEligibility.REPLAYABLE,
                HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS,
                HistoryMigrationEligibility.ALREADY_CURRENT,
            }
            and item.target_assessment_id is not None
        )
        if (
            supported_endpoint
            and cohort in actionable_cohorts
            and cohort not in excluded_cohorts
        ):
            cohort_items.setdefault(cohort, []).append(item)

    policy = ComparisonPolicy()
    pair_priorities: list[tuple[float, int, str, str, tuple[str, str]]] = []
    with closing(SQLiteHealthStore(store.path, read_only=True)._connect()) as connection:
        existing_ids = {
            row["comparison_id"]
            for row in connection.execute(
                "SELECT comparison_id FROM comparisons"
            )
        }
        for cohort, items in cohort_items.items():
            candidates: list[dict[str, Any]] = []
            for item in items:
                if item.target_assessment_id is None:
                    raise HealthMigrationError(
                        "Eligible history has no deterministic target assessment"
                    )
                source = connection.execute(
                    """SELECT a.assessed_at, a.network_roster_revision,
                              o.observation_id, o.observed_at, o.completeness
                       FROM assessments a JOIN observations o USING (observation_id)
                       WHERE a.assessment_id=? AND o.network_id=? AND o.dataset_id=?""",
                    (item.source_assessment_id, *cohort),
                ).fetchone()
                if source is None:
                    raise HealthMigrationError(
                        "Health history changed after comparison reservation preview"
                    )
                candidates.append(
                    {
                        "assessment_id": item.target_assessment_id,
                        "assessed_at": source["assessed_at"],
                        "network_roster_revision": source[
                            "network_roster_revision"
                        ],
                        "observation_id": source["observation_id"],
                        "observed_at": source["observed_at"],
                        "completeness": source["completeness"],
                    }
                )
            candidates.sort(
                key=lambda row: (
                    SQLiteHealthStore._utc_instant(row["observed_at"]),
                    row["network_roster_revision"],
                    SQLiteHealthStore._utc_instant(row["assessed_at"]),
                    row["assessment_id"],
                ),
                reverse=True,
            )
            for after in candidates:
                if after["completeness"] != "complete":
                    continue
                after_time = SQLiteHealthStore._utc_instant(
                    after["observed_at"]
                )
                if any(
                    candidate["observation_id"] != after["observation_id"]
                    and SQLiteHealthStore._utc_instant(
                        candidate["observed_at"]
                    ) == after_time
                    for candidate in candidates
                ):
                    continue
                before_ids: list[str] = []
                adjacent = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate["completeness"] == "complete"
                        and SQLiteHealthStore._utc_instant(
                            candidate["observed_at"]
                        ) < after_time
                    ),
                    None,
                )
                if adjacent is not None:
                    before_ids.append(adjacent["assessment_id"])
                for interval in COMPARISON_INTERVALS:
                    before = resolve_interval_candidate(
                        candidates,
                        after_observed_at=after["observed_at"],
                        interval=interval,
                        complete_only=True,
                    )
                    if before is not None:
                        before_ids.append(str(before["assessment_id"]))
                for priority, before_id in enumerate(dict.fromkeys(before_ids)):
                    pair_id = comparison_id(
                        before_id, after["assessment_id"], policy
                    )
                    if pair_id not in existing_ids:
                        pair_priorities.append(
                            (
                                -after_time.timestamp(),
                                priority,
                                before_id,
                                after["assessment_id"],
                                cohort,
                            )
                        )

        pair_priorities.sort()
        unique_pairs: list[
            tuple[float, int, str, str, tuple[str, str]]
        ] = []
        seen_pair_ids = set(existing_ids)
        for pair in pair_priorities:
            pair_id = comparison_id(pair[2], pair[3], policy)
            if pair_id in seen_pair_ids:
                continue
            seen_pair_ids.add(pair_id)
            unique_pairs.append(pair)
        available_slots = max(0, 2000 - len(existing_ids))
        reserved = unique_pairs[:available_slots]
        reserved_by_cohort: dict[tuple[str, str], set[str]] = {}
        for pair in reserved:
            reserved_by_cohort.setdefault(pair[4], set()).add(
                comparison_id(pair[2], pair[3], policy)
            )
        deferred_by_cohort: dict[tuple[str, str], int] = {}
        for pair in unique_pairs[available_slots:]:
            deferred_by_cohort[pair[4]] = (
                deferred_by_cohort.get(pair[4], 0) + 1
            )
    return (
        existing_ids,
        {
            cohort: frozenset(ids)
            for cohort, ids in reserved_by_cohort.items()
        },
        deferred_by_cohort,
    )


def migrate_health_history(
    store: SQLiteHealthStore,
    *,
    data_dir: Path,
    target_policy: HealthPolicy,
    inventory: HistoryMigrationInventory,
    backup_output: Path,
) -> dict[str, Any]:
    """Back up, revalidate, and migrate replayable network/dataset cohorts."""
    report = history_migration_report(
        inventory, dry_run=False, target_policy=target_policy
    )

    from td_system_backups import create_backup, validate_backup

    backup_manifest: dict[str, Any] | None = None
    backup_manifest_digest: str | None = None
    allowed_assessment_ids = frozenset(
        item.target_assessment_id
        for item in inventory.items
        if item.target_assessment_id is not None
    )
    groups: dict[tuple[str, str], list[HistoryMigrationInventoryItem]] = {}
    for item in inventory.items:
        groups.setdefault((item.network_id, item.dataset_id), []).append(item)
    existing_comparison_ids, reserved_by_cohort, deferred_by_cohort = (
        _comparison_reservations(store, inventory)
    )
    committed_comparison_ids: set[str] = set()
    completed_cohorts: list[dict[str, Any]] = []

    for (network_id, dataset_id), all_members in sorted(groups.items()):
        cohort = [
            item for item in all_members
            if item.eligibility in {
                HistoryMigrationEligibility.REPLAYABLE,
                HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS,
            } or (
                item.eligibility is HistoryMigrationEligibility.ALREADY_CURRENT
                and item.target_assessment_id is not None
                and item.target_assessment_id != item.preferred_assessment_id
            )
        ]
        invalid_members = [
            item for item in all_members
            if item.eligibility is HistoryMigrationEligibility.INVALID
        ]
        if invalid_members:
            completed_cohorts.append(
                {
                    "networkId": network_id,
                    "datasetId": dataset_id,
                    "outcome": "failed",
                    "reason": "cohort-contains-invalid-retained-evidence",
                    "invalidObservationIds": [
                        item.observation_id for item in invalid_members
                    ],
                }
            )
            continue
        if not cohort:
            continue
        connection = store._connect_existing_write()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise HealthMigrationError(
                    "Health store is busy; stop active writers and retry"
                ) from exc
            expected_comparison_ids = (
                existing_comparison_ids | committed_comparison_ids
            )
            locked_comparison_ids = {
                row["comparison_id"]
                for row in connection.execute(
                    "SELECT comparison_id FROM comparisons"
                )
            }
            if locked_comparison_ids != expected_comparison_ids:
                raise HealthMigrationError(
                    "Stored comparisons changed after global migration reservations; rerun the migration"
                )

            locked_inventory = inventory_health_history(
                SQLiteHealthStore(store.path, read_only=True),
                target_policy=target_policy,
                dataset_ids=inventory.dataset_ids,
                network_id=inventory.network_id,
            )
            if (
                locked_inventory.target_contract_digest
                != inventory.target_contract_digest
                or locked_inventory.source_inventory_digest
                != inventory.source_inventory_digest
            ):
                raise HealthMigrationError(
                    "Health history changed after preview; rerun the migration"
                )

            if backup_manifest is None:
                backup_manifest = create_backup(data_dir, backup_output)
                validated_manifest = validate_backup(backup_output)
                if validated_manifest != backup_manifest:
                    raise HealthMigrationError(
                        "Completed backup does not match its validated manifest"
                    )
                backup_manifest_digest = _digest(backup_manifest)
                backup_inventory = inventory_health_history(
                    SQLiteHealthStore(
                        backup_output / HOBAT_DATABASE_FILENAME,
                        read_only=True,
                    ),
                    target_policy=target_policy,
                    dataset_ids=inventory.dataset_ids,
                    network_id=inventory.network_id,
                )
                if (
                    backup_inventory.source_inventory_digest
                    != inventory.source_inventory_digest
                ):
                    raise HealthMigrationError(
                        "Backup health inventory differs from the locked source"
                    )

            current_schema = int(
                connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
            )
            if current_schema not in {7, 8}:
                raise HealthMigrationError(
                    f"Health-history migration does not support schema {current_schema}"
                )
            if current_schema == 7:
                SQLiteHealthStore._ensure_schema_v8(connection)

            plans = []
            created_count = 0
            reused_count = 0
            preference_count = 0
            for item in sorted(cohort, key=lambda value: value.observation_id):
                fresh_item = next(
                    (
                        current for current in locked_inventory.items
                        if current.observation_id == item.observation_id
                        and current.dataset_id == dataset_id
                        and current.network_id == network_id
                    ),
                    None,
                )
                if fresh_item is None or (
                    fresh_item.eligibility not in {
                        HistoryMigrationEligibility.REPLAYABLE,
                        HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS,
                    }
                    and not (
                        fresh_item.eligibility
                        is HistoryMigrationEligibility.ALREADY_CURRENT
                        and fresh_item.target_assessment_id is not None
                        and fresh_item.target_assessment_id
                        != fresh_item.preferred_assessment_id
                    )
                ):
                    raise HealthMigrationError(
                        f"Migration source changed eligibility: {item.observation_id}"
                    )
                row, observation, inputs, assessment = _replay_item(
                    connection, fresh_item, target_policy
                )
                if assessment.assessment_id == row["assessment_id"]:
                    plans.append(
                        (fresh_item, row, observation, inputs, assessment, None)
                    )
                    continue
                existing = connection.execute(
                    """SELECT target_assessment_id, migration_id
                       FROM health_assessment_upgrades
                       WHERE source_assessment_id=? AND target_contract_digest=?""",
                    (row["assessment_id"], inventory.target_contract_digest),
                ).fetchone()
                if existing is not None:
                    if existing["target_assessment_id"] != assessment.assessment_id:
                        raise sqlite3.DatabaseError(
                            "Existing assessment upgrade conflicts with deterministic target"
                        )
                    if not _assessment_matches(connection, assessment):
                        raise sqlite3.DatabaseError(
                            "Existing assessment upgrade target is corrupt"
                        )
                    reused_count += 1
                    migration_id = existing["migration_id"]
                else:
                    target_row = connection.execute(
                        "SELECT 1 FROM assessments WHERE assessment_id=?",
                        (assessment.assessment_id,),
                    ).fetchone()
                    if target_row is not None:
                        raise sqlite3.DatabaseError(
                            "Deterministic target assessment exists without its upgrade mapping"
                        )
                    created_count += 1
                    migration_id = None
                plans.append(
                    (fresh_item, row, observation, inputs, assessment, migration_id)
                )

            plans.sort(
                key=lambda item: (
                    SQLiteHealthStore._utc_instant(item[1]["observed_at"]),
                    item[1]["observation_id"],
                )
            )
            migration_id = (
                f"health-migration:{uuid.uuid4().hex}"
                if created_count
                else None
            )
            now = datetime.now(timezone.utc).isoformat()
            if migration_id is not None:
                reason_counts: dict[str, int] = {}
                for item, *_ in plans:
                    for domain in item.unavailable_domains:
                        reason_counts[domain] = reason_counts.get(domain, 0) + 1
                connection.execute(
                    """INSERT INTO health_history_migrations
                       (migration_id, network_id, dataset_id,
                        target_contract_digest, source_inventory_digest,
                        input_schema_version, output_schema_version, started_at,
                        committed_at, backup_path, backup_manifest_digest,
                        counts_json, reasons_json)
                       VALUES (?, ?, ?, ?, ?, ?, 8, ?, ?, ?, ?, ?, ?)""",
                    (
                        migration_id,
                        network_id,
                        dataset_id,
                        inventory.target_contract_digest,
                        inventory.source_inventory_digest,
                        current_schema,
                        now,
                        now,
                        str(backup_output.resolve()),
                        backup_manifest_digest,
                        json.dumps(
                            {
                                "created": created_count,
                                "reused": reused_count,
                                "preferencesChanged": 0,
                            },
                            sort_keys=True,
                        ),
                        json.dumps(reason_counts, sort_keys=True),
                    ),
                )

            cohort_items: list[dict[str, Any]] = []
            comparisons_stored = 0
            comparisons_deferred = 0
            for item, row, observation, inputs, assessment, existing_migration_id in plans:
                if assessment.assessment_id == row["assessment_id"]:
                    preference = connection.execute(
                        """SELECT assessment_id, selection_basis_assessment_id,
                                  origin, migration_id
                           FROM health_assessment_preferences WHERE observation_id=?""",
                        (observation.observation_id,),
                    ).fetchone()
                    if (
                        preference is None
                        or preference["selection_basis_assessment_id"]
                        != row["assessment_id"]
                    ):
                        raise sqlite3.DatabaseError(
                            "Native preference basis changed during policy reversion"
                        )
                    if (
                        preference["assessment_id"] != row["assessment_id"]
                        or preference["origin"] != "native"
                        or preference["migration_id"] is not None
                    ):
                        connection.execute(
                            """UPDATE health_assessment_preferences
                               SET assessment_id=?, selection_basis_assessment_id=?,
                                   origin='native', migration_id=NULL
                               WHERE observation_id=?""",
                            (
                                row["assessment_id"],
                                row["assessment_id"],
                                observation.observation_id,
                            ),
                        )
                        preference_count += 1
                    cohort_items.append(
                        {
                            "observationId": item.observation_id,
                            "sourceAssessmentId": row["assessment_id"],
                            "targetAssessmentId": row["assessment_id"],
                            "created": False,
                            "reused": True,
                            "preferenceRestoredToNative": True,
                            "unavailableDomains": list(item.unavailable_domains),
                        }
                    )
                    continue
                edge_migration_id = existing_migration_id or migration_id
                if edge_migration_id is None:
                    raise sqlite3.DatabaseError(
                        "Assessment upgrade has no committed migration lineage"
                    )
                if existing_migration_id is None:
                    if not store._insert_assessment(connection, assessment):
                        raise sqlite3.DatabaseError(
                            "Deterministic target assessment was not inserted"
                        )
                    connection.execute(
                        """INSERT INTO health_assessment_upgrades
                           (source_assessment_id, target_contract_digest,
                            target_assessment_id, migration_id, replay_input_digest,
                            unavailable_domains_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            row["assessment_id"],
                            inventory.target_contract_digest,
                            assessment.assessment_id,
                            edge_migration_id,
                            assessment.policy_digest,
                            json.dumps(item.unavailable_domains),
                        ),
                    )
                preference = connection.execute(
                    """SELECT assessment_id, selection_basis_assessment_id,
                              origin, migration_id
                       FROM health_assessment_preferences WHERE observation_id=?""",
                    (observation.observation_id,),
                ).fetchone()
                if (
                    preference is None
                    or preference["selection_basis_assessment_id"]
                    != row["assessment_id"]
                ):
                    raise sqlite3.DatabaseError(
                        "Native selection basis changed during cohort migration"
                    )
                if (
                    preference["assessment_id"] != assessment.assessment_id
                    or preference["origin"] != "migration"
                    or preference["migration_id"] != edge_migration_id
                ):
                    connection.execute(
                        """UPDATE health_assessment_preferences
                           SET assessment_id=?, selection_basis_assessment_id=?,
                               origin='migration', migration_id=?
                           WHERE observation_id=?""",
                        (
                            assessment.assessment_id,
                            row["assessment_id"],
                            edge_migration_id,
                            observation.observation_id,
                        ),
                    )
                    preference_count += 1
                cohort_items.append(
                    {
                        "observationId": item.observation_id,
                        "sourceAssessmentId": row["assessment_id"],
                        "targetAssessmentId": assessment.assessment_id,
                        "created": existing_migration_id is None,
                        "reused": existing_migration_id is not None,
                        "unavailableDomains": list(item.unavailable_domains),
                    }
                )

            reserved_comparison_ids = reserved_by_cohort.get(
                (network_id, dataset_id), frozenset()
            )
            comparison_endpoints: list[tuple[Observation, Assessment]] = []
            for item in all_members:
                if (
                    item.eligibility
                    not in {
                        HistoryMigrationEligibility.REPLAYABLE,
                        HistoryMigrationEligibility.REPLAYABLE_WITH_GAPS,
                        HistoryMigrationEligibility.ALREADY_CURRENT,
                    }
                    or item.target_assessment_id is None
                ):
                    continue
                endpoint = store._endpoint(
                    connection, item.target_assessment_id
                )
                if endpoint is None:
                    raise sqlite3.DatabaseError(
                        "Preferred comparison endpoint is missing after migration"
                    )
                comparison_endpoints.append(endpoint)
            comparison_endpoints.sort(
                key=lambda endpoint: (
                    SQLiteHealthStore._utc_instant(
                        endpoint[0].observed_at
                    ),
                    endpoint[0].observation_id,
                )
            )
            for observation, assessment in comparison_endpoints:
                stored, deferred = store._auto_compare(
                    connection,
                    observation,
                    assessment,
                    allowed_assessment_ids=allowed_assessment_ids,
                    reserved_comparison_ids=reserved_comparison_ids,
                    enforce_retention=False,
                )
                comparisons_stored += stored
                comparisons_deferred += deferred
            if comparisons_deferred != deferred_by_cohort.get(
                (network_id, dataset_id), 0
            ):
                raise sqlite3.DatabaseError(
                    "Migration comparison reservations do not match the locked endpoint inventory"
                )
            new_comparison_ids = {
                row["comparison_id"]
                for row in connection.execute(
                    "SELECT comparison_id FROM comparisons"
                )
            } - expected_comparison_ids
            if not new_comparison_ids.issubset(reserved_comparison_ids):
                raise sqlite3.DatabaseError(
                    "Migration inserted a comparison outside its global reservation"
                )

            if migration_id is not None:
                connection.execute(
                    """UPDATE health_history_migrations SET counts_json=?
                       WHERE migration_id=?""",
                    (
                        json.dumps(
                            {
                                "created": created_count,
                                "reused": reused_count,
                                "preferencesChanged": preference_count,
                                "comparisonsStored": comparisons_stored,
                                "comparisonsDeferred": comparisons_deferred,
                            },
                            sort_keys=True,
                        ),
                        migration_id,
                    ),
                )
            SQLiteHealthStore._set_current_assessment(
                connection, network_id, dataset_id
            )
            fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise sqlite3.DatabaseError(
                    "Health migration cohort violates foreign-key integrity"
                )
            connection.commit()
            committed_comparison_ids.update(new_comparison_ids)
            cohort_report = {
                "networkId": network_id,
                "datasetId": dataset_id,
                "outcome": "committed",
                "migrationId": migration_id,
                "created": created_count,
                "reused": reused_count,
                "preferencesChanged": preference_count,
                "comparisonsStored": comparisons_stored,
                "comparisonsDeferred": comparisons_deferred,
                "items": cohort_items,
            }
            completed_cohorts.append(cohort_report)
        except Exception as exc:
            connection.rollback()
            failed_cohort = {
                "networkId": network_id,
                "datasetId": dataset_id,
                "outcome": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }
            completed_cohorts.append(failed_cohort)
            report["totals"]["failed"] += len(cohort)
            report["outcome"] = (
                "partial-with-failures"
                if len(completed_cohorts) > 1
                else "failed"
            )
            report["cohorts"] = completed_cohorts
            report["backupPath"] = (
                str(backup_output.resolve()) if backup_manifest else None
            )
            report["totals"]["created"] = sum(
                int(item.get("created", 0)) for item in completed_cohorts
            )
            report["totals"]["reused"] = sum(
                int(item.get("reused", 0)) for item in completed_cohorts
            )
            report["totals"]["preferencesChanged"] = sum(
                int(item.get("preferencesChanged", 0))
                for item in completed_cohorts
            )
            report["totals"]["comparisonsStored"] = sum(
                int(item.get("comparisonsStored", 0))
                for item in completed_cohorts
            )
            report["totals"]["comparisonsDeferred"] = sum(
                int(item.get("comparisonsDeferred", 0))
                for item in completed_cohorts
            )
            return report
        finally:
            connection.close()

    report["cohorts"] = completed_cohorts
    report["backupPath"] = str(backup_output.resolve()) if backup_manifest else None
    report["totals"]["created"] = sum(
        int(item.get("created", 0)) for item in completed_cohorts
    )
    report["totals"]["reused"] = sum(
        int(item.get("reused", 0)) for item in completed_cohorts
    )
    report["totals"]["preferencesChanged"] = sum(
        int(item.get("preferencesChanged", 0)) for item in completed_cohorts
    )
    report["totals"]["comparisonsStored"] = sum(
        int(item.get("comparisonsStored", 0)) for item in completed_cohorts
    )
    report["totals"]["comparisonsDeferred"] = sum(
        int(item.get("comparisonsDeferred", 0))
        for item in completed_cohorts
    )
    if report["totals"]["failed"]:
        report["outcome"] = (
            "partial-with-failures"
            if (
                report["totals"]["created"]
                or report["totals"]["reused"]
                or report["totals"]["preferencesChanged"]
            )
            else "failed"
        )
    elif report["totals"]["unsupported"]:
        report["outcome"] = "partial-with-unsupported"
    elif (
        report["totals"]["created"]
        or report["totals"]["reused"]
        or report["totals"]["preferencesChanged"]
    ):
        report["outcome"] = "complete"
    return report
