"""Versioned, read-only collection facts supplied by the owning collectors.

This module does not qualify source evidence, reconcile records, or infer
attempts. A history contains only attempts explicitly supplied by its owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, cast

VOCABULARY_VERSION = 1

Status = Literal["completed", "skipped", "partial", "failed", "other"]
Coverage = Literal["complete", "partial", "absent", "unknown"]
TableClass = Literal["answered", "not_provided", "unanswered", "legacy", "unavailable"]
Response = Literal["observed", "not_observed", "unknown"]
ResponseEvidence = Literal["direct", "ping", "qualified_diagnostic", "unknown"]
RecoveryState = Literal["none", "attempted", "recovered", "unknown"]
RecoveryKind = Literal["none", "same_set_retry", "request_fallback", "child_rloc", "child_detail", "unknown"]
AttemptKind = Literal["initial", "same_set_retry", "request_fallback", "child_rloc", "child_detail", "unknown"]
StatusPhase = Literal["initial", "effective"]

STATUSES = ("completed", "skipped", "partial", "failed", "other")
_COVERAGE = frozenset(("complete", "partial", "absent", "unknown"))
_TABLE_CLASSES = frozenset(("answered", "not_provided", "unanswered", "legacy", "unavailable"))
_RESPONSES = frozenset(("observed", "not_observed", "unknown"))
_RESPONSE_EVIDENCE = frozenset(("direct", "ping", "qualified_diagnostic", "unknown"))
_RECOVERY_STATES = frozenset(("none", "attempted", "recovered", "unknown"))
_RECOVERY_KINDS = frozenset(("none", "same_set_retry", "request_fallback", "child_rloc", "child_detail", "unknown"))
_ATTEMPT_KINDS = frozenset(("initial", "same_set_retry", "request_fallback", "child_rloc", "child_detail", "unknown"))

# Stable source codes only: exception messages and unlisted codes stay unknown.
REASON_LABELS: Mapping[str, str] = MappingProxyType({
    "unknown": "Unknown reason",
    "unresolved_mesh_local_iid": "Address could not be resolved",
    "already_collected": "Already collected",
    "conflicting_evidence": "Conflicting evidence",
    "conflicting_child_mode": "Conflicting child mode",
    "conflicting_parent_identity": "Conflicting parent identity",
    "parent_unavailable": "Parent unavailable",
    "parent_evidence_unavailable": "Parent evidence unavailable",
    "parent_child_table_missing": "Parent child table missing",
    "invalid_parent_rloc16": "Invalid parent RLOC16",
    "parent_rloc16_not_router": "Parent RLOC16 is not a router",
    "parent_router_id_out_of_range": "Parent router ID out of range",
    "malformed_child_table": "Malformed child table",
    "invalid_child_entry": "Invalid child entry",
    "identity_missing": "Identity missing",
    "identity_changed": "Identity changed",
    "identity_conflict": "Identity conflict",
    "rloc16_mismatch": "RLOC16 mismatch",
    "unresolved_prior_action": "Prior action unresolved",
    "child_passes_disabled": "Child passes disabled",
    "malformed-outcome": "Malformed outcome",
    "malformed-target": "Malformed target",
    "incomplete-target": "Incomplete target",
    "malformed-expansion-target": "Malformed expansion target",
    "incomplete-expansion-target": "Incomplete expansion target",
    "expansion-issue": "Expansion issue",
    "malformed-expansion-issue": "Malformed expansion issue",
    "unverified-recovery-evidence": "Recovery evidence not verified",
    "unsupported-destination-type": "Unsupported destination type",
    "missing-target-identity": "Target identity missing",
    "partial-table-returned": "Partial table returned",
    "ineligible-failure": "Failure not eligible",
    "ambiguous-target": "Ambiguous target",
    "target-identity-changed": "Target identity changed",
    "witness-missing": "Witness missing",
    "witness-stale": "Witness stale",
    "children-uncovered": "Children not covered",
    "diagnostic-no-response": "No diagnostic response",
    "diagnostic-invalid-evidence": "Invalid diagnostic evidence",
    "diagnostic-result-missing": "Diagnostic result missing",
    "diagnostic-result-reused": "Diagnostic result reused",
    "diagnostic-identity-mismatch": "Diagnostic identity mismatch",
    "diagnostic-response-stale": "Diagnostic response stale",
    "unsupported-contract": "Unsupported evidence contract",
    "scope-changed": "Network scope changed",
    "scope-unavailable": "Network scope unavailable",
    "witness-binding-mismatch": "Witness binding mismatch",
    "witness-identity-mismatch": "Witness identity mismatch",
    "answered": "Table answered",
    "not-provided-qualified": "Table not provided",
    "ambiguous_target": "Ambiguous target",
    "disabled": "Disabled",
    "skip_devices": "Device collection skipped",
    "skip_diagnostics": "Diagnostics skipped",
    "skip_mesh_diagnostics": "Mesh diagnostics skipped",
    "not_requested": "Not requested",
    "petition_rejected": "Petition rejected",
    "dtls_failed": "DTLS failed",
    "border_router_unreachable": "Border router unreachable",
    "no_credentials": "Credentials unavailable",
    "no_source": "Source unavailable",
    "rest_unreachable": "REST source unreachable",
    "rest_protocol": "REST protocol error",
    "timeout": "Timed out",
    "in_progress": "In progress",
    "meshcop_no_responses_yet": "No MeshCoP responses yet",
    "rest_no_responses_yet": "No REST responses yet",
})


def _validate_version(version: int) -> None:
    if type(version) is not int or version != VOCABULARY_VERSION:
        raise ValueError(f"Unsupported collection outcome vocabulary version: {version!r}")


def _member(name: str, value: str, allowed: frozenset[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"Invalid {name}: {value!r}")


def normalize_status(value: str | None) -> Status:
    """Translate a common status; source-specific translations belong to owners."""
    return cast(Status, value) if isinstance(value, str) and value in STATUSES else "other"


def normalize_reason(code: str | None) -> str:
    """Return a bounded histogram key without interpreting arbitrary error text."""
    return code if isinstance(code, str) and code in REASON_LABELS else "unknown"


def _optional_text(name: str, value: str | None) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")


@dataclass(frozen=True)
class CollectionAttempt:
    """One already-verified attempt, in the order supplied by its owner."""

    kind: AttemptKind
    status: Status | str | None
    evidence_ref: str | None = None
    original_status: str | None = None
    diagnostics: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        _member("attempt kind", self.kind, _ATTEMPT_KINDS)
        _optional_text("status", self.status)
        _optional_text("original_status", self.original_status)
        _optional_text("evidence_ref", self.evidence_ref)
        raw = self.status
        object.__setattr__(self, "original_status", self.original_status if self.original_status is not None else raw)
        status = normalize_status(raw)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "diagnostics", ("status_other",) if status == "other" else ())


@dataclass(frozen=True)
class CollectionOutcome:
    """A scoped view of independent, already-validated collection facts."""

    source: str
    command: str
    stage: str
    target: str
    initial_status: Status | str | None
    effective_status: Status | str | None
    coverage: Coverage = "unknown"
    table_class: TableClass = "unavailable"
    response: Response = "unknown"
    response_evidence: ResponseEvidence = "unknown"
    recovery_state: RecoveryState = "unknown"
    recovery_kind: RecoveryKind = "unknown"
    original_status: str | None = None
    original_effective_status: str | None = None
    original_reason_code: str | None = None
    attempts: tuple[CollectionAttempt, ...] = ()
    version: int = VOCABULARY_VERSION
    diagnostics: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        _validate_version(self.version)
        for name in ("source", "command", "stage", "target"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a nonempty string")
        for name in ("initial_status", "effective_status", "original_status", "original_effective_status", "original_reason_code"):
            _optional_text(name, getattr(self, name))
        for name, allowed in (
            ("coverage", _COVERAGE), ("table_class", _TABLE_CLASSES),
            ("response", _RESPONSES), ("response_evidence", _RESPONSE_EVIDENCE),
            ("recovery_state", _RECOVERY_STATES), ("recovery_kind", _RECOVERY_KINDS),
        ):
            _member(name, getattr(self, name), allowed)
        initial, effective = self.initial_status, self.effective_status
        object.__setattr__(self, "original_status", self.original_status if self.original_status is not None else initial)
        object.__setattr__(self, "original_effective_status", self.original_effective_status if self.original_effective_status is not None else effective)
        object.__setattr__(self, "initial_status", normalize_status(initial))
        object.__setattr__(self, "effective_status", normalize_status(effective))
        object.__setattr__(self, "diagnostics", tuple(
            name + "_other" for name in ("initial_status", "effective_status")
            if getattr(self, name) == "other"
        ))
        attempts = tuple(self.attempts)
        if not all(isinstance(item, CollectionAttempt) for item in attempts):
            raise TypeError("attempts must contain CollectionAttempt values")
        object.__setattr__(self, "attempts", attempts)

    @property
    def reason_code(self) -> str:
        return normalize_reason(self.original_reason_code)

    @property
    def reason_label(self) -> str:
        return REASON_LABELS[self.reason_code]

    @property
    def display_label(self) -> str:
        if self.table_class == "not_provided":
            return "Not provided"
        return {
            "completed": "Request completed", "skipped": "Request skipped",
            "partial": "Request partial", "failed": "Request failed",
            "other": "Request outcome unknown",
        }[self.effective_status]

    @property
    def recovery_summary(self) -> str:
        if self.recovery_state == "none":
            return "No recovery"
        if self.recovery_state == "unknown":
            return "Recovery unknown"
        path = {
            "none": None, "unknown": None, "same_set_retry": "retry",
            "request_fallback": "alternate request", "child_rloc": "child RLOC",
            "child_detail": "child detail",
        }[self.recovery_kind]
        verb = "Recovered" if self.recovery_state == "recovered" else "Recovery attempted"
        return f"{verb} by {path}" if path else verb

    def event_fields(self) -> dict[str, object]:
        """Return fresh log-only fields; callers supply source, command and stage."""
        return {
            "target": self.target,
            "initial_status": self.initial_status,
            "effective_status": self.effective_status,
            "coverage": self.coverage,
            "table_class": self.table_class,
            "response": self.response,
            "response_evidence": self.response_evidence,
            "recovery_state": self.recovery_state,
            "recovery_kind": self.recovery_kind,
            "reason_code": self.reason_code,
            "reason_label": self.reason_label,
            "display_label": self.display_label,
            "recovery_summary": self.recovery_summary,
            "original_status": self.original_status,
            "original_effective_status": self.original_effective_status,
            "original_reason_code": self.original_reason_code,
            "version": self.version,
            "diagnostics": list(self.diagnostics),
            "attempts": [
                {
                    "kind": attempt.kind,
                    "status": attempt.status,
                    "original_status": attempt.original_status,
                    "evidence_ref": attempt.evidence_ref,
                    "diagnostics": list(attempt.diagnostics),
                }
                for attempt in self.attempts
            ],
        }


@dataclass(frozen=True)
class CollectionSummary:
    population: int
    terminal_statuses: Mapping[str, int]
    reasons: Mapping[str, int]
    verified_attempts: int
    verified_attempt_kinds: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "terminal_statuses", MappingProxyType(dict(self.terminal_statuses)))
        object.__setattr__(self, "reasons", MappingProxyType(dict(self.reasons)))
        object.__setattr__(self, "verified_attempt_kinds", MappingProxyType(dict(self.verified_attempt_kinds)))

    def event_fields(self) -> dict[str, object]:
        return {
            "version": VOCABULARY_VERSION,
            "population": self.population,
            "terminal_statuses": dict(self.terminal_statuses),
            "reasons": {key: count for key, count in self.reasons.items() if count},
            "verified_attempts": self.verified_attempts,
            "verified_attempt_kinds": dict(self.verified_attempt_kinds),
        }


def summarize_outcomes(
    outcomes: Iterable[CollectionOutcome], *,
    version: int = VOCABULARY_VERSION,
    status_phase: StatusPhase = "effective",
) -> CollectionSummary:
    """Count each supplied view once; attempts are a separate evidence unit."""
    _validate_version(version)
    _member("status_phase", status_phase, frozenset(("initial", "effective")))
    statuses = dict.fromkeys(STATUSES, 0)
    reasons = dict.fromkeys(REASON_LABELS, 0)
    population = attempts = 0
    attempt_kinds: dict[str, int] = {}
    for outcome in outcomes:
        if not isinstance(outcome, CollectionOutcome):
            raise TypeError("outcomes must contain CollectionOutcome values")
        _validate_version(outcome.version)
        population += 1
        status = outcome.initial_status if status_phase == "initial" else outcome.effective_status
        statuses[status] += 1
        reasons[outcome.reason_code] += 1
        attempts += len(outcome.attempts)
        for attempt in outcome.attempts:
            attempt_kinds[attempt.kind] = attempt_kinds.get(attempt.kind, 0) + 1
    return CollectionSummary(population, statuses, reasons, attempts, attempt_kinds)


def log_outcome_summary(
    outcomes: Iterable[CollectionOutcome] | None, *,
    source: str, command: str, stage: str, status_phase: StatusPhase = "effective",
) -> None:
    """Keep unavailable evidence distinct from a known empty population."""
    from td_logging import log_event

    _member("status_phase", status_phase, frozenset(("initial", "effective")))
    fields = (
        summarize_outcomes(outcomes, status_phase=status_phase).event_fields()
        if outcomes is not None else {"version": VOCABULARY_VERSION}
    )
    log_event(
        "outcome_summary", source=source, command=command, stage=stage,
        status_phase=status_phase,
        availability="available" if outcomes is not None else "unavailable",
        **fields,
    )
