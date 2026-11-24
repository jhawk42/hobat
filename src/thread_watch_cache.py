"""Verified reads for the Thread Watch final and unknown-scope companion."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from td_const import THREAD_WATCH_DEVICES_FILENAME
from util_data import network_scope_path


THREAD_WATCH_SCOPE_FILENAME = network_scope_path(
    THREAD_WATCH_DEVICES_FILENAME
).name


class ThreadWatchCacheError(ValueError):
    """The Thread Watch final/sidecar pair is not safely readable."""

    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ThreadWatchVerifiedPair:
    snapshot: bytes
    companion: bytes
    snapshot_mtime: float
    companion_mtime: float
    snapshot_digest: str
    companion_digest: str

    @property
    def publication_mtime(self) -> float:
        return min(self.snapshot_mtime, self.companion_mtime)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ThreadWatchCacheError(
                "Thread Watch scope contains duplicate JSON keys",
                reason="invalid-sidecar",
            )
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ThreadWatchCacheError(
        "Thread Watch scope contains a non-finite JSON number",
        reason="invalid-sidecar",
    )


def _float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _constant(value)
    return parsed


def _read_stable(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            content = stream.read()
            after = os.fstat(stream.fileno())
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ThreadWatchCacheError(
            "Cannot read Thread Watch cache pair", reason="read-error"
        ) from exc
    before_signature = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        len(content),
    )
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        len(content),
    )
    if before_signature != after_signature:
        raise ThreadWatchCacheError(
            "Thread Watch cache changed during read",
            reason="changed-during-read",
        )
    return content, after


def read_thread_watch_pair(snapshot_path: Path) -> ThreadWatchVerifiedPair:
    snapshot_path = Path(snapshot_path)
    companion_path = network_scope_path(snapshot_path)
    try:
        snapshot, snapshot_stat = _read_stable(snapshot_path)
    except FileNotFoundError as exc:
        raise ThreadWatchCacheError(
            "Thread Watch snapshot is missing", reason="missing-snapshot"
        ) from exc
    try:
        companion, companion_stat = _read_stable(companion_path)
    except FileNotFoundError as exc:
        raise ThreadWatchCacheError(
            "Thread Watch scope companion is missing", reason="missing-sidecar"
        ) from exc
    try:
        scope = json.loads(
            companion.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_float,
            parse_constant=_constant,
        )
    except ThreadWatchCacheError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ThreadWatchCacheError(
            "Thread Watch scope companion is invalid", reason="invalid-sidecar"
        ) from exc
    required = {
        "extPanId",
        "networkName",
        "provenance",
        "reason",
        "observedAt",
        "sources",
        "snapshotSha256",
    }
    observed_at = scope.get("observedAt") if isinstance(scope, dict) else None
    try:
        observed_at_valid = (
            isinstance(observed_at, str)
            and datetime.fromisoformat(observed_at).tzinfo is not None
        )
    except ValueError:
        observed_at_valid = False
    if (
        not isinstance(scope, dict)
        or set(scope) != required
        or scope.get("extPanId") is not None
        or scope.get("networkName") is not None
        or scope.get("provenance") != "unknown"
        or scope.get("reason") != "thread-watch-inventory-unscoped"
        or not observed_at_valid
        or scope.get("sources") != ["thread-watch"]
        or not isinstance(scope.get("snapshotSha256"), str)
    ):
        raise ThreadWatchCacheError(
            "Thread Watch scope companion is not the required unknown scope",
            reason="invalid-sidecar",
        )
    snapshot_digest = hashlib.sha256(snapshot).hexdigest()
    if scope["snapshotSha256"] != snapshot_digest:
        raise ThreadWatchCacheError(
            "Thread Watch scope digest does not match the snapshot",
            reason="digest-mismatch",
        )
    return ThreadWatchVerifiedPair(
        snapshot=snapshot,
        companion=companion,
        snapshot_mtime=snapshot_stat.st_mtime,
        companion_mtime=companion_stat.st_mtime,
        snapshot_digest=snapshot_digest,
        companion_digest=hashlib.sha256(companion).hexdigest(),
    )


def thread_watch_cache_error(snapshot_path: Path) -> str | None:
    try:
        read_thread_watch_pair(snapshot_path)
    except ThreadWatchCacheError as exc:
        return exc.reason
    return None
