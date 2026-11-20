"""Local-calendar scheduler and its durable execution state."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone, tzinfo
import json
import logging
import os
from pathlib import Path
import re
import tempfile

from td_health_cli import DEFAULT_HEALTH_PURGE_KEEP_DAYS
from td_network_identity import canonical_ext_pan_id
from td_scheduler_lock import SCHEDULER_STATE_FILENAME, acquire_scheduler_lock
from util_data import TD_EXT_PAN_ID_ENV_VAR

_LOG = logging.getLogger(__name__)
_UTC = timezone.utc
_STATE_LIMIT = 16_384
_RUN_COUNTS = ("command_count", "skip_count", "failure_count", "cancelled_count")
ENABLED_ENV = "TD_SCHEDULER_ENABLED"


@dataclass(frozen=True)
class SchedulerSettings:
    enabled: bool = False
    start_time: time = time(4, 20)
    retention_override: int | None = None
    ext_pan_id: str | None = None

    @classmethod
    def from_env(cls, enabled: bool, env: Mapping[str, str]) -> "SchedulerSettings":
        start = env.get("TD_SCHEDULER_START_TIME", "04:20")
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", start):
            raise ValueError("TD_SCHEDULER_START_TIME must use 24-hour HH:MM")
        raw_days = env.get("TD_SCHEDULER_KEEP_DAYS")
        override = None
        if raw_days is not None:
            try:
                override = int(raw_days) if re.fullmatch(r"[0-9]+", raw_days) else 0
            except ValueError:
                override = 0
            if override < 1:
                raise ValueError("TD_SCHEDULER_KEEP_DAYS must be a positive integer")
        ext_pan_id = None
        if enabled:
            try:
                ext_pan_id = canonical_ext_pan_id(env.get(TD_EXT_PAN_ID_ENV_VAR))
            except ValueError as exc:
                raise ValueError("Enabled scheduler requires a valid TD_EXT_PAN_ID") from exc
        return cls(enabled, time.fromisoformat(start), override, ext_pan_id)

    @property
    def keep_days(self) -> int:
        return self.retention_override or DEFAULT_HEALTH_PURGE_KEEP_DAYS

    def purge_args(self) -> tuple[str, ...]:
        args = ("health", "purge", "--apply", "--json")
        if self.retention_override is not None:
            args += ("--keep-days", str(self.retention_override))
        return args


def is_second_sunday(day: date) -> bool:
    return day.weekday() == 6 and 8 <= day.day <= 14


def next_slot(
    now: datetime, start_time: time, claimed: date | None = None, zone: tzinfo | None = None,
) -> datetime:
    """Find the first future slot; None for zone means the process's OS local time."""
    local_now = now.astimezone(zone)
    day = local_now.date()
    if claimed is not None and claimed >= day:
        day = claimed + timedelta(days=1)
    while True:
        wall = datetime.combine(day, start_time)
        # Round-trip through UTC: reject gaps and choose the first instant in a fold.
        candidates = set()
        for fold in (0, 1):
            candidate = wall.replace(tzinfo=zone, fold=fold)
            instant = candidate.astimezone(_UTC)
            if instant.astimezone(zone).replace(tzinfo=None) == wall:
                candidates.add(instant)
        if candidates and (first := min(candidates)) > now.astimezone(_UTC):
            return first.astimezone(zone)
        day += timedelta(days=1)


class SchedulerStateError(RuntimeError):
    """The local execution state is not safe to use."""


@dataclass(frozen=True)
class RunRecord:
    job_id: str
    trigger: str
    mode: str
    started_at: str
    slot: date | None
    status: str
    finished_at: str | None = None
    counts: dict[str, int] | None = None

    def to_json(self) -> dict:
        return {
            "job_id": self.job_id, "trigger": self.trigger, "mode": self.mode,
            "started_at": self.started_at, "slot": self.slot.isoformat() if self.slot else None,
            "status": self.status, "finished_at": self.finished_at, "counts": self.counts,
        }

    @classmethod
    def from_json(cls, payload: dict, *, active: bool) -> "RunRecord":
        if not isinstance(payload, dict) or set(payload) != {
            "job_id", "trigger", "mode", "started_at", "slot", "status", "finished_at", "counts",
        }:
            raise ValueError("invalid run metadata")
        job_id = payload["job_id"]
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", job_id):
            raise ValueError("invalid job ID")
        trigger, mode, status = (payload[k] for k in ("trigger", "mode", "status"))
        slot = _read_date(payload["slot"])
        if (trigger, mode) not in {("scheduled", "full"), ("manual", "full"), ("manual", "quick")}:
            raise ValueError("invalid trigger or mode")
        if (slot is not None) != (trigger == "scheduled"):
            raise ValueError("invalid run slot")
        allowed = {"running"} if active else {"done", "error", "cancelled", "interrupted"}
        if status not in allowed:
            raise ValueError("invalid run status")
        started, finished = (payload[k] for k in ("started_at", "finished_at"))
        for stamp in (started,) if active else (started, finished):
            if not isinstance(stamp, str) or len(stamp) > 40 or datetime.fromisoformat(stamp).utcoffset() is None:
                raise ValueError("invalid run timestamp")
        if active and finished is not None:
            raise ValueError("active run already finished")
        counts = payload["counts"]
        if counts is not None and (
            active or not isinstance(counts, dict) or set(counts) != set(_RUN_COUNTS)
            or any(type(value) is not int or not 0 <= value <= 100 for value in counts.values())
        ):
            raise ValueError("invalid run counts")
        return cls(job_id, trigger, mode, started, slot, status, finished, counts)


def _read_date(value: str | None) -> date | None:
    if value is None:
        return None
    day = date.fromisoformat(value)
    if value != day.isoformat() or day >= date.max - timedelta(days=2):
        raise ValueError("invalid slot date")
    return day


@dataclass(frozen=True)
class SchedulerState:
    claimed: date | None = None
    monthly: date | None = None
    active: RunRecord | None = None
    last: RunRecord | None = None
    last_skip: str | None = None

    @classmethod
    def load(cls, path: Path) -> "SchedulerState":
        try:
            with path.open("rb") as stream:
                encoded = stream.read(_STATE_LIMIT + 1)
        except FileNotFoundError:
            return cls()
        if len(encoded) > _STATE_LIMIT:
            raise ValueError("oversized scheduler state")
        raw = json.loads(encoded)
        if (not isinstance(raw, dict) or set(raw) != {
            "version", "claimed", "monthly", "active", "last", "last_skip",
        } or type(raw["version"]) is not int or raw["version"] != 1):
            raise ValueError("unsupported scheduler state format")
        claimed, monthly = _read_date(raw["claimed"]), _read_date(raw["monthly"])
        if monthly and (not claimed or monthly > claimed or not is_second_sunday(monthly)):
            raise ValueError("invalid monthly claim")
        active = RunRecord.from_json(raw["active"], active=True) if raw["active"] is not None else None
        last = RunRecord.from_json(raw["last"], active=False) if raw["last"] is not None else None
        for record in (active, last):
            if record and record.slot and (claimed is None or record.slot > claimed):
                raise ValueError("run has no durable claim")
        skip = raw["last_skip"]
        if skip not in (None, "skipped-busy", "missed") or (skip and claimed is None):
            raise ValueError("invalid slot disposition")
        return cls(claimed, monthly, active, last, skip)

    def save(self, path: Path) -> None:
        payload = {
            "version": 1,
            "claimed": self.claimed.isoformat() if self.claimed else None,
            "monthly": self.monthly.isoformat() if self.monthly else None,
            "active": self.active.to_json() if self.active else None,
            "last": self.last.to_json() if self.last else None,
            "last_skip": self.last_skip,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f"{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            staging = Path(stream.name)
            try:
                json.dump(payload, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(staging, path)
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                staging.unlink(missing_ok=True)


class Scheduler:
    def __init__(
        self, data_dir: Path, settings: SchedulerSettings, *,
        clock: Callable[[], datetime] = lambda: datetime.now(_UTC),
        zone: tzinfo | None = None,
    ):
        self.data_dir = data_dir.resolve()
        self.settings = settings
        self.clock = clock
        self.zone = zone
        self.paused = False
        self.error: str | None = None
        self.next_run: datetime | None = None
        self.admission_epoch = 0
        self.state = SchedulerState()
        self._changed = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._path = self.data_dir / SCHEDULER_STATE_FILENAME
        self._timer_task: asyncio.Task | None = None

    def _arm(self) -> None:
        self.next_run = None
        if self.settings.enabled and not self.paused and not self.error:
            self.next_run = next_slot(
                self.clock(), self.settings.start_time, self.state.claimed, self.zone,
            )

    def set_paused(self, paused: bool) -> None:
        if self.paused != paused:
            self.paused = paused
            self._arm()
            self._changed.set()

    def _disable(self, exc: Exception) -> SchedulerStateError:
        self.error = f"Cannot use scheduler state in {self.data_dir}: {type(exc).__name__}"
        self.next_run = None
        self._changed.set()
        _LOG.error("%s; scheduled execution is disabled", self.error)
        return SchedulerStateError(self.error)

    async def lifetime(self, dispatch: Callable[[datetime], Awaitable[None]] | None = None):
        if not self.settings.enabled:
            yield
            return
        with acquire_scheduler_lock(self.data_dir):
            try:
                self.state = await asyncio.to_thread(SchedulerState.load, self._path)
                if self.state.active:
                    await self.finish(self.state.active.job_id, "interrupted")
            except (OSError, ValueError, TypeError) as exc:
                self._disable(exc)
            except SchedulerStateError:
                pass  # The failed persistence already disabled this owner.
            self._arm()
            local = self.clock().astimezone(self.zone)
            _LOG.info(
                "Scheduler timezone=%s offset=%s next_local=%s next_utc=%s",
                local.tzname(), local.strftime("%z"), self.next_run,
                self.next_run.astimezone(_UTC) if self.next_run else None,
            )
            if dispatch:
                self._timer_task = asyncio.create_task(self._timer(dispatch))
            try:
                yield
            finally:
                await self.stop_timer()

    async def stop_timer(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
            await asyncio.gather(self._timer_task, return_exceptions=True)
            self._timer_task = None

    async def _save(self, state: SchedulerState) -> None:
        if self.error:
            raise SchedulerStateError(self.error)

        async def write():
            try:
                await asyncio.to_thread(state.save, self._path)
            except OSError as exc:
                raise self._disable(exc) from exc
            self.state = state

        task = asyncio.create_task(write())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task  # Do not release the owner lock or permit another state write yet.
            raise

    async def begin(self, job_id: str, *, quick: bool, slot: date | None) -> bool:
        async with self._write_lock:
            if self.state.active or (slot and self.state.claimed and slot <= self.state.claimed):
                return False
            record = RunRecord(
                job_id, "scheduled" if slot else "manual", "quick" if quick else "full",
                self.clock().astimezone(_UTC).isoformat(), slot, "running",
            )
            await self._save(replace(
                self.state, active=record,
                claimed=slot or self.state.claimed,
                monthly=slot if slot and is_second_sunday(slot) else self.state.monthly,
                last_skip=None if slot else self.state.last_skip,
            ))
            return True

    async def finish(self, job_id: str, status: str, result: Mapping | None = None) -> None:
        async with self._write_lock:
            active = self.state.active
            if active and active.job_id == job_id:
                counts = None
                if result and all(type(result.get(key)) is int and 0 <= result[key] <= 100 for key in _RUN_COUNTS):
                    counts = {key: result[key] for key in _RUN_COUNTS}
                await self._save(replace(self.state, active=None, last=replace(
                    active, status=status, finished_at=self.clock().astimezone(_UTC).isoformat(), counts=counts,
                )))

    async def record_skip(self, slot: date, reason: str) -> None:
        async with self._write_lock:
            if self.state.claimed is None or slot > self.state.claimed:
                await self._save(replace(self.state, claimed=slot, last_skip=reason))
                _LOG.info("Scheduler slot=%s status=%s", slot, reason)

    async def _check_slot(self, dispatch: Callable[[datetime], Awaitable[None]]) -> None:
        slot = self.next_run
        now = self.clock()
        if slot is None or now.astimezone(_UTC) < slot.astimezone(_UTC):
            return
        self._arm()
        if self.state.claimed and slot.date() <= self.state.claimed:
            return
        if now.astimezone(self.zone).date() != slot.date():
            await self.record_skip(slot.date(), "missed")
        elif self.state.active:
            await self.record_skip(slot.date(), "skipped-busy")
        else:
            await dispatch(slot)

    async def _timer(self, dispatch: Callable[[datetime], Awaitable[None]]) -> None:
        while not self.error:
            self._changed.clear()
            try:
                await self._check_slot(dispatch)
            except SchedulerStateError:
                return
            if self.next_run is None:
                await self._changed.wait()
                continue
            until = self.next_run.astimezone(_UTC) - self.clock().astimezone(_UTC)
            try:
                await asyncio.wait_for(self._changed.wait(), min(30, max(0, until.total_seconds())))
            except asyncio.TimeoutError:
                pass
