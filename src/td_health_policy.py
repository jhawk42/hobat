"""Validated, versioned health policy defaults."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


POLICY_FILENAME = "td-health-policy.json"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    return value


_SNAPSHOT_V1_RAW: dict[str, Any] = {
        "version": "snapshot-v1",
        "offlineConsecutiveCompleteObservations": 2,
        "thresholds": {
            "totalMacErrorRatio": {"unstable": 0.01, "high": 0.05},
            "totalMacDiscardRatio": {"unstable": 0.02, "high": 0.08},
            "routerNeighborFrameErrorRate": {
                "unstable": 0.05,
                "high": 0.10,
                "critical": 0.30,
            },
            "routerNeighborMessageErrorRate": {
                "unstable": 0.05,
                "high": 0.10,
                "critical": 0.30,
            },
            "childFrameErrorRate": {"unstable": 0.10, "high": 0.25},
            "childMessageErrorRate": {"unstable": 0.01, "high": 0.05},
            "observedLq3Ratio": {"unstableBelow": 0.60, "highBelow": 0.35},
            "observedLq1Ratio": {"unstable": 0.20, "high": 0.35},
            "childLinkQuality": {"unstableAtOrBelow": 2, "highAtOrBelow": 1},
            "rssi": {"unstableBelow": -70.0, "highBelow": -80.0},
            "childLinkMargin": {"unstableBelow": 20.0},
            "borderRouterCount": {"unstableAtOrBelow": 1},
            "routerCount": {"unstableAtOrBelow": 1},
        },
    }
SNAPSHOT_V1: Mapping[str, Any] = _freeze(_SNAPSHOT_V1_RAW)
_REQUIRED_THRESHOLD_BANDS = {
    metric: frozenset(bands)
    for metric, bands in _SNAPSHOT_V1_RAW["thresholds"].items()
}


class HealthPolicyError(ValueError):
    """Raised when an operator health policy is invalid."""


@dataclass(frozen=True)
class HealthPolicy:
    version: str
    digest: str
    offline_consecutive_complete_observations: int
    thresholds: Mapping[str, Mapping[str, float | int]]


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_policy(raw: object) -> HealthPolicy:
    if not isinstance(raw, dict):
        raise HealthPolicyError("Health policy must be a JSON object")
    version = raw.get("version")
    consecutive = raw.get("offlineConsecutiveCompleteObservations")
    thresholds = raw.get("thresholds")
    if not isinstance(version, str) or not version:
        raise HealthPolicyError("Health policy requires version")
    if not isinstance(consecutive, int) or consecutive < 2:
        raise HealthPolicyError(
            "offlineConsecutiveCompleteObservations must be at least 2"
        )
    if not isinstance(thresholds, dict) or not thresholds:
        raise HealthPolicyError("Health policy requires thresholds")
    if set(thresholds) != set(_REQUIRED_THRESHOLD_BANDS):
        raise HealthPolicyError("Health policy must define every snapshot-v1 threshold")
    normalized: dict[str, Mapping[str, float | int]] = {}
    for metric, bands in thresholds.items():
        if not isinstance(metric, str) or not isinstance(bands, dict) or not bands:
            raise HealthPolicyError("Each threshold requires named numeric bands")
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in bands.values()
        ):
            raise HealthPolicyError(f"Threshold bands must be numeric: {metric}")
        if set(bands) != set(_REQUIRED_THRESHOLD_BANDS[metric]):
            raise HealthPolicyError(f"Invalid threshold bands: {metric}")
        normalized[metric] = MappingProxyType(dict(bands))
    return HealthPolicy(
        version=version,
        digest=_canonical_digest(raw),
        offline_consecutive_complete_observations=consecutive,
        thresholds=MappingProxyType(normalized),
    )


def load_health_policy(config_dir: Path | None = None) -> HealthPolicy:
    if config_dir is None or not (config_dir / POLICY_FILENAME).exists():
        return _validate_policy(json.loads(json.dumps(_SNAPSHOT_V1_RAW)))
    path = config_dir / POLICY_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HealthPolicyError(f"Cannot load health policy: {exc}") from exc
    return _validate_policy(raw)