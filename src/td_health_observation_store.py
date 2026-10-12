"""Store boundary for health observations and assessments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from td_health_observation_model import Assessment, Observation


HOBAT_DATABASE_FILENAME = "hobat_v1.db"
MAX_OBSERVATIONS = 2000


class HealthStoreError(RuntimeError):
    """Base error for health observation storage."""


class HealthStoreFutureSchemaError(HealthStoreError):
    """Raised when the database schema is newer than this application."""


class HealthStoreMigrationError(HealthStoreError):
    """Raised when the health-store schema cannot be inspected or upgraded."""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        recovery_backup_path: str | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.recovery_backup_path = recovery_backup_path


@dataclass(frozen=True)
class StoreResult:
    observation_created: bool
    assessment_created: bool


@dataclass(frozen=True)
class PurgeResult:
    cutoff: str | None
    deleted: Mapping[str, int]
    dry_run: bool


class HealthObservationStore(Protocol):
    def save_processing_result(
        self, observation: Observation, assessment: Assessment
    ) -> StoreResult: ...

    def expected_device_ids(self, network_id: str) -> frozenset[str]: ...

    def upsert_expected_device(
        self, network_id: str, device_id: str, label: str | None
    ) -> None: ...

    def purge_before(
        self, cutoff: datetime, *, dry_run: bool = False
    ) -> PurgeResult: ...

    def purge_all(self, *, dry_run: bool = False) -> PurgeResult: ...

    def purge_device(
        self,
        device_id: str,
        *,
        network_id: str | None = None,
        dry_run: bool = False,
    ) -> PurgeResult: ...