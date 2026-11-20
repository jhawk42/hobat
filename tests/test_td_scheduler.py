import asyncio
from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

import pytest

from td_scheduler import (
    Scheduler,
    SchedulerSettings,
    SchedulerState,
    SchedulerStateError,
    is_second_sunday,
    next_slot,
)
from td_scheduler_lock import SCHEDULER_STATE_FILENAME, SchedulerLockError

UTC = timezone.utc
ENABLED = SchedulerSettings.from_env(True, {"TD_EXT_PAN_ID": "01:23:45:67:89:ab:cd:ef"})


def run_async(test):
    @wraps(test)
    def run(*args, **kwargs):
        asyncio.run(test(*args, **kwargs))

    return run


@pytest.mark.parametrize("env", [
    {"TD_SCHEDULER_START_TIME": "24:00"},
    {"TD_SCHEDULER_START_TIME": "4:20"},
    {"TD_SCHEDULER_START_TIME": "04:20:00"},
    {"TD_SCHEDULER_KEEP_DAYS": "0"},
    {"TD_SCHEDULER_KEEP_DAYS": "-1"},
    {"TD_SCHEDULER_KEEP_DAYS": "1.5"},
    {"TD_SCHEDULER_KEEP_DAYS": ""},
])
def test_invalid_settings_rejected_even_when_disabled(env):
    with pytest.raises(ValueError, match="TD_SCHEDULER_"):
        SchedulerSettings.from_env(False, env)


def test_configured_retention_only_adds_cli_override_when_supplied():
    assert ENABLED.ext_pan_id == "0123456789abcdef"
    assert ENABLED.keep_days == 10
    assert ENABLED.purge_args() == ("health", "purge", "--apply", "--json")
    override = SchedulerSettings.from_env(False, {"TD_SCHEDULER_KEEP_DAYS": "30"})
    assert override.keep_days == 30
    assert override.purge_args()[-2:] == ("--keep-days", "30")
    with pytest.raises(ValueError, match="TD_EXT_PAN_ID"):
        SchedulerSettings.from_env(True, {})


def test_calendar_handles_leap_day_year_rollover_and_monthly_slot():
    for month in range(1, 13):
        days = [date(2024, month, day) for day in range(1, 29)]
        sundays = [day for day in days if day.weekday() == 6]
        assert [day for day in days if is_second_sunday(day)] == sundays[1:2]
    for now, expected in [
        (datetime(2024, 2, 28, 4, 20, tzinfo=UTC), datetime(2024, 2, 29, 4, 20, tzinfo=UTC)),
        (datetime(2024, 12, 31, 5, tzinfo=UTC), datetime(2025, 1, 1, 4, 20, tzinfo=UTC)),
    ]:
        assert next_slot(now, ENABLED.start_time, zone=UTC) == expected


def test_spring_gap_is_skipped_and_fall_fold_is_not_replayed():
    zone = ZoneInfo("America/New_York")
    assert next_slot(datetime(2026, 3, 8, 5, tzinfo=UTC), time(2, 30), zone=zone).astimezone(
        UTC
    ) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    assert next_slot(datetime(2026, 11, 1, 4, tzinfo=UTC), time(1, 30), zone=zone).astimezone(
        UTC
    ) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert next_slot(datetime(2026, 11, 1, 6, tzinfo=UTC), time(1, 30), zone=zone).date() == date(2026, 11, 2)


@run_async
async def test_disabled_scheduler_leaves_no_state_or_owner(tmp_path):
    async for _ in Scheduler(tmp_path, SchedulerSettings()).lifetime():
        async for _ in Scheduler(tmp_path, ENABLED).lifetime():
            assert not (tmp_path / SCHEDULER_STATE_FILENAME).exists()


@run_async
async def test_claim_survives_restart_and_backward_clock(tmp_path):
    now = datetime(2026, 11, 8, 4, tzinfo=UTC)  # second Sunday
    original = Scheduler(tmp_path, ENABLED, clock=lambda: now, zone=UTC)
    async for _ in original.lifetime():
        original.set_paused(True)
        with pytest.raises(SchedulerLockError):
            async for _ in Scheduler(tmp_path, ENABLED).lifetime():
                pytest.fail("second owner admitted")
        assert await original.begin("job-1", quick=False, slot=now.date())

    restarted = Scheduler(tmp_path, ENABLED, clock=lambda: now - timedelta(days=1), zone=UTC)
    async for _ in restarted.lifetime():
        assert not restarted.paused
        assert restarted.state.monthly == now.date()
        assert restarted.state.last.status == "interrupted"
        assert restarted.next_run.date() == date(2026, 11, 9)
        assert not await restarted.begin("job-2", quick=False, slot=now.date())


@run_async
async def test_resume_skips_elapsed_slot_late_live_wake_and_busy_are_distinct(tmp_path):
    now = datetime(2026, 11, 7, 4, tzinfo=UTC)
    scheduler = Scheduler(tmp_path, ENABLED, zone=UTC, clock=lambda: now)
    dispatched = []

    async def dispatch(slot):
        dispatched.append(slot.date())
        await scheduler.begin("job-1", quick=False, slot=slot.date())

    async for _ in scheduler.lifetime():
        scheduler.set_paused(True)
        now = now.replace(hour=5)
        scheduler.set_paused(False)
        assert scheduler.next_run.date() == date(2026, 11, 8)
        now += timedelta(days=1)
        await scheduler._check_slot(dispatch)
        assert dispatched == [date(2026, 11, 8)]
        now += timedelta(days=1)
        await scheduler._check_slot(dispatch)
        assert scheduler.state.last_skip == "skipped-busy"
        assert dispatched == [date(2026, 11, 8)]
        await scheduler.finish("job-1", "done")
        now += timedelta(days=2)
        await scheduler._check_slot(dispatch)
        assert scheduler.state.claimed == date(2026, 11, 10)
        assert scheduler.state.last_skip == "missed"
        assert dispatched == [date(2026, 11, 8)]


@run_async
async def test_corrupt_state_stays_intact_and_unwritable_state_disables_admission(tmp_path, monkeypatch):
    path = tmp_path / SCHEDULER_STATE_FILENAME
    path.write_text('{"version":999}', encoding="utf-8")
    scheduler = Scheduler(tmp_path, ENABLED)
    async for _ in scheduler.lifetime():
        assert scheduler.error and scheduler.next_run is None
        with pytest.raises(SchedulerStateError):
            await scheduler.begin("job-1", quick=False, slot=None)
    assert path.read_text(encoding="utf-8") == '{"version":999}'
    path.unlink()

    def fail_write(*_args):
        raise PermissionError("test fixture cannot be written")

    monkeypatch.setattr(SchedulerState, "save", fail_write)
    scheduler = Scheduler(tmp_path, ENABLED)
    async for _ in scheduler.lifetime():
        with pytest.raises(SchedulerStateError):
            await scheduler.begin("job-1", quick=True, slot=None)
        assert scheduler.error and scheduler.state.active is None
