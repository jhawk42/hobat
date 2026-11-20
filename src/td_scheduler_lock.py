"""Shared scheduler ownership and restore coordination."""

from __future__ import annotations

import fcntl
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEDULER_STATE_FILENAME = ".td-scheduler-state.json"
SCHEDULER_LOCK_FILENAME = ".td-scheduler.lock"
_MOUNT_ESCAPE = re.compile(rb"\\([0-7]{3})")


class SchedulerLockError(RuntimeError):
    """The data directory is already owned by a scheduler or restore."""


def is_mount_root(data_dir: Path) -> bool:
    if os.path.ismount(data_dir):
        return True
    # Linux same-filesystem bind mounts are invisible to os.path.ismount().
    try:
        with open("/proc/self/mountinfo", "rb") as mounts:
            target = os.fsencode(data_dir.resolve())
            for record in mounts:
                mountpoint = record.split(b" ", 5)[4]
                if _MOUNT_ESCAPE.sub(lambda match: bytes([int(match[1], 8)]), mountpoint) == target:
                    return True
    except FileNotFoundError:
        pass  # Non-Linux hosts have no mountinfo.
    return False


@contextmanager
def acquire_scheduler_lock(data_dir: Path) -> Iterator[None]:
    data_dir = Path(data_dir).resolve()
    if is_mount_root(data_dir):
        lock_path = data_dir / SCHEDULER_LOCK_FILENAME
    else:
        data_dir.parent.mkdir(parents=True, exist_ok=True)
        lock_path = data_dir.parent / f".{data_dir.name}{SCHEDULER_LOCK_FILENAME}"
    with lock_path.open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SchedulerLockError(
                f"Scheduler lock is busy for {data_dir}; stop the scheduler-enabled "
                "server before restoring or starting another scheduler; "
                "wait for any active restore to finish"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
