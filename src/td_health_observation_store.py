"""Store boundary for health observations and assessments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from td_health_observation_model import Assessment, Observation


HOBAT_DATABASE_FILENAME = "hobat_v1.db"
MAX_OBSERVATIONS = 2000


class HealthStoreError(RuntimeError):
    """Base error for health observation storage."""


class HealthStoreFutureSchemaError(HealthStoreError):
    """Raised when the database schema is newer than this application."""


@dataclass(frozen=True)
class StoreResult:
    observation_created: bool
    assessment_created: bool


class HealthObservationStore(Protocol):
    def save_processing_result(
        self, observation: Observation, assessment: Assessment
    ) -> StoreResult: ...

    def expected_device_ids(self, network_id: str) -> frozenset[str]: ...

    def upsert_expected_device(
        self, network_id: str, device_id: str, label: str | None
    ) -> None: ...