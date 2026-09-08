"""Cache-only Thread health processing orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from merge_dataset import SOURCE_PRECEDENCE
from td_device_fields import get_canonical_ext_address, normalize_input_record
from td_health_evaluator import evaluate_observation
from td_health_manifest import HealthDataset, load_health_manifest
from td_health_observation_model import (
    Assessment,
    Completeness,
    DeviceSample,
    MetricSample,
    Observation,
    RelationshipSample,
    SourceEvidence,
    device_id_from_ext_address,
    network_id_from_ext_pan_id,
    relationship_id,
)
from td_health_policy import HealthPolicy
from td_health_sqlite import SQLiteHealthStore


class HealthProcessingError(RuntimeError):
    """Raised when cached inputs cannot be processed safely."""


@dataclass(frozen=True)
class ProcessingResult:
    observation: Observation
    assessment: Assessment
    observation_created: bool | None
    assessment_created: bool | None


def _stable_read(path: Path) -> tuple[Any, str, int]:
    try:
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise HealthProcessingError(f"Cannot read {path.name}: {exc}") from exc
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise HealthProcessingError(f"Input changed while reading: {path.name}")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HealthProcessingError(f"Invalid JSON in {path.name}: {exc}") from exc
    return payload, hashlib.sha256(content).hexdigest(), after.st_mtime_ns


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        return [payload]
    return []


def _outcome_state(payload: Any) -> Completeness:
    if not isinstance(payload, dict):
        return Completeness.PARTIAL
    if payload.get("partial") is True:
        return Completeness.PARTIAL
    results = payload.get("deviceResults")
    if isinstance(results, list):
        statuses = [item.get("status") for item in results if isinstance(item, dict)]
        if not statuses or any(status != "completed" for status in statuses):
            return Completeness.PARTIAL
        if isinstance(payload.get("completedAt"), str):
            return Completeness.COMPLETE
    return Completeness.DEGRADED


def _percent_fraction(value: Any, datasource_id: str) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if datasource_id == "otbr-cli":
        return number / 100.0
    return number


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _omr_prefix_from_identity(identity: Mapping[str, Any]) -> str | None:
    precomputed = identity.get("prefixOmrIpv6AddrPrefix")
    if isinstance(precomputed, str) and precomputed:
        return precomputed
    prefix = identity.get("prefixOmr")
    if isinstance(prefix, str) and prefix:
        return prefix.split("/")[0].rstrip(":")
    return None


def _normalize_samples(
    dataset: HealthDataset, payloads: Mapping[str, Any]
) -> tuple[
    tuple[DeviceSample, ...],
    tuple[RelationshipSample, ...],
    tuple[MetricSample, ...],
    tuple[str, ...],
    Mapping[str, tuple[str, ...]],
]:
    devices: dict[str, dict[str, Any]] = {}
    rloc_devices: dict[str, str] = {}
    normalized_by_file: dict[str, list[dict[str, Any]]] = {}
    ordered_files = sorted(
        dataset.files, key=lambda filename: (-SOURCE_PRECEDENCE.get(filename, 0), filename)
    )
    for filename in ordered_files:
        normalized_by_file[filename] = [
            normalize_input_record(record, source=filename)
            for record in _records(payloads[filename])
        ]
        for record in normalized_by_file[filename]:
            ext_address = get_canonical_ext_address(record)
            try:
                device_id = device_id_from_ext_address(ext_address)
            except ValueError:
                continue
            current = devices.setdefault(
                device_id,
                {
                    "extAddress": ext_address,
                    "role": None,
                    "state": None,
                    "isBorderRouter": False,
                    "sourceFiles": set(),
                    "ipv6Addresses": set(),
                },
            )
            current["sourceFiles"].add(filename)
            for field in ("role", "state"):
                if current[field] is None and isinstance(record.get(field), str):
                    current[field] = record[field]
            current["isBorderRouter"] = current["isBorderRouter"] or record.get("isBorderRouter") is True
            addresses = record.get("ipv6Addresses")
            if isinstance(addresses, list):
                current["ipv6Addresses"].update(addr for addr in addresses if isinstance(addr, str))
            rloc = record.get("rloc16")
            if isinstance(rloc, str):
                rloc_devices[rloc.lower()] = device_id

    relationships: dict[str, RelationshipSample] = {}
    metrics: dict[tuple[str, str, str], MetricSample] = {}
    duplicate_relationship_ids: set[str] = set()
    for filename, records in normalized_by_file.items():
        seen_in_file: set[str] = set()
        for record in records:
            reporter_id: str | None = None
            try:
                reporter_id = device_id_from_ext_address(get_canonical_ext_address(record))
            except ValueError:
                rloc = record.get("rloc16")
                if isinstance(rloc, str):
                    reporter_id = rloc_devices.get(rloc.lower())
            if reporter_id is None:
                continue
            mac_counters = record.get("macCounters")
            if isinstance(mac_counters, dict):
                denominator = _number(mac_counters.get("ifTotalPkts"))
                for field, metric_name in (
                    ("ifTotalErrorsTotalPktsRatio", "totalMacErrorRatio"),
                    ("ifTotalDiscardsTotalPktsRatio", "totalMacDiscardRatio"),
                ):
                    value = _number(mac_counters.get(field))
                    if value is not None and denominator is not None and denominator > 0:
                        metrics[(reporter_id, metric_name, filename)] = MetricSample(
                            reporter_id, metric_name, value, "ratio", denominator, filename
                        )
            mle_counters = record.get("mleCounters")
            if isinstance(mle_counters, dict):
                for field, metric_name in (
                    ("newParentCount", "parentChanges"),
                    ("partIdChangesCount", "partitionIdChanges"),
                    ("betterPartIdAttachAttemptsCount", "betterPartitionAttachAttempts"),
                    ("totalParentPartitionChangesCount", "totalParentPartitionChanges"),
                ):
                    value = _number(mle_counters.get(field))
                    if value is not None:
                        metrics[(reporter_id, metric_name, filename)] = MetricSample(
                            reporter_id, metric_name, value, "count", None, filename
                        )
            time_statistics = record.get("timeStatistics")
            if isinstance(time_statistics, dict):
                detached_disabled = _number(time_statistics.get("detachedDisabledPct"))
                if detached_disabled is None:
                    detached = _number(time_statistics.get("detachedPct"))
                    disabled = _number(time_statistics.get("disabledPct"))
                    if detached is not None or disabled is not None:
                        detached_disabled = (detached or 0.0) + (disabled or 0.0)
                for value, metric_name in (
                    (_number(time_statistics.get("routerPct")), "routerRolePercent"),
                    (detached_disabled, "detachedDisabledPercent"),
                ):
                    if value is not None:
                        metrics[(reporter_id, metric_name, filename)] = MetricSample(
                            reporter_id, metric_name, value, "percent", None, filename
                        )
            error = record.get("error")
            if isinstance(error, dict) and error.get("type") == "ResponseTimeout":
                metrics[(reporter_id, "diagnosticTimeout", filename)] = MetricSample(
                    reporter_id, "diagnosticTimeout", 1.0, "flag", None, filename
                )
            for field, metric_name in (
                ("totalLink1", "observedLinkQuality1Count"),
                ("totalLink2", "observedLinkQuality2Count"),
                ("totalLink3", "observedLinkQuality3Count"),
            ):
                value = _number(record.get(field))
                if value is not None:
                    metrics[(reporter_id, metric_name, filename)] = MetricSample(
                        reporter_id, metric_name, value, "count", None, filename
                    )
            for child_field in ("routerNeighbors", "children", "childTable"):
                children = record.get(child_field)
                if not isinstance(children, list):
                    continue
                for raw_child in children:
                    if not isinstance(raw_child, dict):
                        continue
                    child = normalize_input_record(raw_child, source=filename)
                    try:
                        child_id = device_id_from_ext_address(get_canonical_ext_address(child))
                    except ValueError:
                        child_rloc = child.get("rloc16")
                        child_id = rloc_devices.get(str(child_rloc).lower())
                    if child_id is None or child_id == reporter_id:
                        continue
                    if child_id not in devices:
                        devices[child_id] = {
                            "extAddress": child_id.removeprefix("extaddr:"),
                            "role": "child" if child_field != "routerNeighbors" else "router",
                            "state": None,
                            "isBorderRouter": False,
                            "sourceFiles": {filename},
                            "ipv6Addresses": set(),
                        }
                    link_id = relationship_id(reporter_id, child_id)
                    if link_id in seen_in_file:
                        duplicate_relationship_ids.add(link_id)
                    seen_in_file.add(link_id)
                    relationships[link_id] = RelationshipSample(
                        relationship_id=link_id,
                        relationship_type=(
                            "router-neighbor" if child_field == "routerNeighbors" else "parent-child"
                        ),
                        from_device_id=reporter_id,
                        to_device_id=child_id,
                        link_quality_in=_integer(child.get("linkQualityIn") or child.get("linkQuality")),
                        link_quality_out=_integer(child.get("linkQualityOut")),
                        average_rssi=_number(child.get("averageRssi")),
                        last_rssi=_number(child.get("lastRssi")),
                        link_margin=_number(child.get("linkMargin")),
                        frame_error_rate=_percent_fraction(child.get("frameErrorRate"), dataset.datasource_id),
                        message_error_rate=_percent_fraction(child.get("messageErrorRate"), dataset.datasource_id),
                        reporter_device_id=reporter_id,
                        source_files=(filename,),
                        queued_message_count=_number(
                            child.get("queuedMessageCount") or child.get("q_msg")
                        ),
                    )

    device_samples = tuple(
        DeviceSample(
            device_id=device_id,
            ext_address=value["extAddress"],
            role=value["role"],
            state=value["state"],
            is_border_router=value["isBorderRouter"],
            source_files=tuple(sorted(value["sourceFiles"])),
        )
        for device_id, value in sorted(devices.items())
    )
    device_ipv6_addresses = {
        device_id: tuple(sorted(value.get("ipv6Addresses", ())))
        for device_id, value in devices.items()
        if value.get("ipv6Addresses")
    }
    return (
        device_samples,
        tuple(relationships[key] for key in sorted(relationships)),
        tuple(metrics[key] for key in sorted(metrics)),
        tuple(sorted(duplicate_relationship_ids)),
        device_ipv6_addresses,
    )


def build_processing_result(
    *,
    data_dir: Path,
    dataset_id: str,
    policy: HealthPolicy,
    allow_partial: bool = False,
    store: SQLiteHealthStore | None = None,
    processing_time: datetime | None = None,
) -> ProcessingResult:
    dataset = load_health_manifest().dataset(dataset_id)
    payloads: dict[str, Any] = {}
    sources: list[SourceEvidence] = []
    mtimes: list[int] = []
    completeness = Completeness.COMPLETE

    required = [*dataset.files, dataset.health_profile.identity_file]
    for filename in required:
        path = data_dir / filename
        try:
            payload, digest, mtime = _stable_read(path)
        except HealthProcessingError:
            completeness = Completeness.PARTIAL
            sources.append(SourceEvidence(filename, "", "identity" if filename == dataset.health_profile.identity_file else "final", "missing-or-invalid"))
            continue
        if not isinstance(payload, (dict, list)):
            completeness = Completeness.PARTIAL
            continue
        payloads[filename] = payload
        mtimes.append(mtime)
        sources.append(SourceEvidence(filename, digest, "identity" if filename == dataset.health_profile.identity_file else "final", "valid"))
        checkpoint = path.with_name(path.name.removesuffix(".json") + ".partial.json")
        if checkpoint.exists() and checkpoint.stat().st_mtime_ns > mtime:
            completeness = Completeness.PARTIAL

    for filename in dataset.health_profile.required_outcomes:
        path = data_dir / filename
        if not path.exists():
            if completeness is Completeness.COMPLETE:
                completeness = Completeness.DEGRADED
            sources.append(SourceEvidence(filename, "", "outcome", "missing"))
            continue
        try:
            payload, digest, mtime = _stable_read(path)
        except HealthProcessingError:
            completeness = Completeness.PARTIAL
            sources.append(SourceEvidence(filename, "", "outcome", "invalid"))
            continue
        state = _outcome_state(payload)
        if state is Completeness.PARTIAL:
            completeness = Completeness.PARTIAL
        elif state is Completeness.DEGRADED and completeness is Completeness.COMPLETE:
            completeness = Completeness.DEGRADED
        mtimes.append(mtime)
        sources.append(SourceEvidence(filename, digest, "outcome", state.value))

    missing = [filename for filename in required if filename not in payloads]
    if missing and not allow_partial:
        raise HealthProcessingError(
            "Required cached inputs are missing or invalid: " + ", ".join(missing)
        )
    if completeness is Completeness.PARTIAL and not allow_partial:
        raise HealthProcessingError("Cached inputs are partial; use --allow-partial to persist provisional evidence")

    identity = payloads.get(dataset.health_profile.identity_file)
    if not isinstance(identity, dict):
        raise HealthProcessingError("A valid identity-context file is required")
    try:
        network_id = network_id_from_ext_pan_id(identity.get("extPanId"))
    except ValueError as exc:
        raise HealthProcessingError(f"Invalid extPanId identity: {exc}") from exc
    network_name = identity.get("networkName")
    if not isinstance(network_name, str):
        network_name = None

    available_finals = {
        filename: payloads[filename]
        for filename in dataset.files
        if filename in payloads
    }
    devices, relationships, metrics, duplicate_relationship_ids, device_ipv6_addresses = _normalize_samples(
        dataset, available_finals
    )
    omr_prefix = _omr_prefix_from_identity(identity)
    source_set_digest = hashlib.sha256(
        "\0".join(f"{source.filename}:{source.digest}" for source in sorted(sources, key=lambda item: item.filename)).encode("utf-8")
    ).hexdigest()
    observed_ns = max(mtimes, default=0)
    observed_at = datetime.fromtimestamp(observed_ns / 1_000_000_000, timezone.utc).isoformat()
    now = processing_time or datetime.now(timezone.utc)
    observation_key = "\0".join((dataset.datasource_id, dataset.dataset_id, network_id, observed_at, source_set_digest))
    observation_id = "observation:" + hashlib.sha256(observation_key.encode("utf-8")).hexdigest()[:24]
    observation = Observation(
        observation_id=observation_id,
        datasource_id=dataset.datasource_id,
        dataset_id=dataset.dataset_id,
        network_id=network_id,
        network_name=network_name,
        observed_at=observed_at,
        ingested_at=now.isoformat(),
        completeness=completeness,
        source_set_digest=source_set_digest,
        sources=tuple(sorted(sources, key=lambda item: item.filename)),
        devices=devices,
        relationships=relationships,
        metrics=metrics,
        duplicate_relationship_ids=duplicate_relationship_ids,
    )
    expected_ids = store.expected_device_ids(network_id) if store else frozenset()
    prior_absences = (
        {
            device_id: store.consecutive_complete_absences(network_id, device_id, observation_id)
            for device_id in expected_ids - {device.device_id for device in devices}
        }
        if store and completeness is Completeness.COMPLETE
        else {}
    )
    assessment = evaluate_observation(
        observation,
        policy,
        profile=dataset.health_profile,
        expected_device_ids=expected_ids,
        prior_complete_absences=prior_absences,
        assessed_at=now.isoformat(),
        omr_prefix=omr_prefix,
        device_ipv6_addresses=device_ipv6_addresses,
    )
    return ProcessingResult(observation, assessment, None, None)


def process_health(**kwargs: Any) -> ProcessingResult:
    store: SQLiteHealthStore = kwargs["store"]
    result = build_processing_result(**kwargs)
    saved = store.save_processing_result(result.observation, result.assessment)
    return ProcessingResult(
        result.observation,
        result.assessment,
        saved.observation_created,
        saved.assessment_created,
    )