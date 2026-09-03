"""Tests for immutable health identities and snapshot-v1 policy."""

from __future__ import annotations

import json

import pytest

from td_health_observation_model import (
    device_id_from_ext_address,
    network_id_from_ext_pan_id,
)
from td_health_policy import HealthPolicyError, load_health_policy


def test_extpan_identity_is_canonical_and_requires_64_bits() -> None:
    assert network_id_from_ext_pan_id("78:B9-775B001C1CBE") == (
        "extpan:78b9775b001c1cbe"
    )
    with pytest.raises(ValueError, match="16 hexadecimal"):
        network_id_from_ext_pan_id("island_27db")


def test_device_identity_rejects_placeholder() -> None:
    assert device_id_from_ext_address("86:72:76:6A:E0:57:81:87") == (
        "extaddr:8672766ae0578187"
    )
    with pytest.raises(ValueError, match="non-placeholder"):
        device_id_from_ext_address("0000000000000000")


def test_snapshot_v1_is_deterministic_and_conservative() -> None:
    first = load_health_policy()
    second = load_health_policy()

    assert first.version == "snapshot-v1"
    assert first.digest == second.digest
    assert first.offline_consecutive_complete_observations == 2
    assert first.offline_poor_device_ratio_threshold == 0.15
    assert first.thresholds["routerNeighborFrameErrorRate"]["critical"] == 0.30
    with pytest.raises(TypeError):
        first.thresholds["rssi"]["unstableBelow"] = -60


def test_invalid_operator_policy_is_rejected(tmp_path) -> None:
    (tmp_path / "td-health-policy.json").write_text(
        json.dumps(
            {
                "version": "unsafe-v1",
                "offlineConsecutiveCompleteObservations": 1,
                "thresholds": {"rssi": {"unstableBelow": -70}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HealthPolicyError, match="at least 2"):
        load_health_policy(tmp_path)


def test_operator_policy_without_offline_ratio_uses_default(tmp_path) -> None:
    default = load_health_policy()
    raw_policy = {
        "version": "custom-v1",
        "offlineConsecutiveCompleteObservations": 3,
        "thresholds": {
            metric: dict(bands)
            for metric, bands in default.thresholds.items()
        },
    }
    (tmp_path / "td-health-policy.json").write_text(
        json.dumps(raw_policy), encoding="utf-8"
    )

    policy = load_health_policy(tmp_path)

    assert policy.offline_poor_device_ratio_threshold == 0.15