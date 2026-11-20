"""Scheduler-only subprocess streaming; no job, state, or workflow ownership."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from td_logging import RUN_COMMAND_ENV, redact_sensitive_output
from util_subprocess import close_subprocess_pipes, signal_subprocess

StreamName = Literal["stdout", "stderr"]
LineCallback = Callable[[StreamName, str], None]
_TAIL_BYTES = 64 * 1024
_READ_BYTES = 8192
_MAX_LINE_BYTES = 1024 * 1024
_TERMINATE_GRACE_S = 2.0
_DATASET_COMMAND = ("node", "dataset", "active", "get")
_DATASET_SAVED = re.compile(rb"Saved ([0-9]{1,12}) records to .+")
_DATASET_DEBUG_BODY = re.compile(r"^(\[[^\]]+\] DEBUG: HTTP (?:Error )?Response body: ).*$")
_SENSITIVE_HINT = re.compile(
    r"credential|network[\s_-]*key|passphrase|password|pskc|pskd|secret|token|\\",
    re.IGNORECASE,
)
_REDACTED_DATASET = "[Redacted active dataset output]"
_OMITTED_LINE = "[Omitted oversized subprocess line]"


@dataclass(frozen=True)
class SchedulerCLIResult:
    returncode: int | None
    timed_out: bool = False
    error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout: str = ""
    stderr: str = ""


@dataclass
class _Tail:
    data: bytearray
    truncated: bool = False

    def append(self, line: str) -> None:
        encoded = (line + "\n").encode("utf-8")
        excess = len(self.data) + len(encoded) - _TAIL_BYTES
        if excess > 0:
            self.truncated = True
            del self.data[:excess]
        self.data.extend(encoded[-_TAIL_BYTES:])

    def text(self) -> str:
        # A byte-boundary cut can split a UTF-8 character at the start.
        return self.data.decode("utf-8", errors="ignore")


async def _drain(
    stream: asyncio.StreamReader | None,
    emit: Callable[[str], None],
    tail: _Tail,
    *,
    dataset_get: bool,
    stream_name: StreamName,
) -> None:
    if stream is None:
        return
    dataset_stdout = dataset_get and stream_name == "stdout"
    saved_count: str | None = None
    dataset_hidden = False
    pending = bytearray()
    oversized = False

    def emit_pending() -> None:
        nonlocal saved_count, dataset_hidden
        if dataset_stdout:
            # Auto-output emits a single `Saved N records to PATH` footer.
            # Without auto-output the body may contain opaque secret TLV, not
            # recognizable by key redaction, followed by a stdout footer.
            if not dataset_hidden:
                match = None if oversized or saved_count is not None else (
                    _DATASET_SAVED.fullmatch(pending.removesuffix(b"\r"))
                )
                if match is not None:
                    saved_count = match[1].decode("ascii")
                else:
                    dataset_hidden = True
                    emit(_REDACTED_DATASET)
        elif oversized:
            tail.truncated = True
            emit(_OMITTED_LINE)
        else:
            line = pending.removesuffix(b"\r").decode("utf-8", errors="replace")
            if dataset_get:
                line = _DATASET_DEBUG_BODY.sub(r"\1" + _REDACTED_DATASET, line)
            # Avoid quadratic scheme matching on long opaque IDs without URI
            # or secret markers. Escapes may conceal keys in JSON.
            if "://" in line or _SENSITIVE_HINT.search(line):
                line = redact_sensitive_output(line)
            emit(line)
        pending.clear()

    while chunk := await stream.read(_READ_BYTES):
        if dataset_hidden:
            continue
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b"\n", offset)
            end = len(chunk) if newline == -1 else newline
            if not oversized:
                if len(pending) + end - offset > _MAX_LINE_BYTES:
                    pending.clear()
                    oversized = True
                else:
                    pending.extend(chunk[offset:end])
            if newline == -1:
                break
            emit_pending()
            if dataset_hidden:
                break
            oversized = False
            offset = newline + 1
        await asyncio.sleep(0)
    if pending or oversized:
        emit_pending()
    if saved_count is not None and not dataset_hidden:
        emit(f"Saved {saved_count} records to active dataset cache")


def _signal(process: asyncio.subprocess.Process, *, force: bool) -> None:
    signal_subprocess(process, force=force)


async def _supervise(
    args: tuple[str, ...],
    data_dir: Path,
    run_cmd: str,
    on_line: LineCallback | None,
    on_process_started: Callable[[asyncio.subprocess.Process], None] | None,
    on_process_ended: Callable[[], None] | None,
    stop: asyncio.Event,
) -> SchedulerCLIResult:
    if stop.is_set():
        return SchedulerCLIResult(None)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    env[RUN_COMMAND_ENV] = run_cmd
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("td_cli.py")),
            "--datadir", str(data_dir), *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=os.name == "posix",
        )
    except Exception:
        # Subprocess/OS exceptions can contain raw filenames, argv, or env.
        return SchedulerCLIResult(None, error="Failed to start scheduler subprocess")

    error = None
    stdout, stderr = _Tail(bytearray()), _Tail(bytearray())
    dataset_get = "otbr-restapi" in args and any(
        args[i:i + len(_DATASET_COMMAND)] == _DATASET_COMMAND
        for i in range(len(args))
    )

    def emit(stream: StreamName, tail: _Tail, line: str) -> None:
        nonlocal error, on_line
        tail.append(line)
        if on_line is not None:
            try:
                on_line(stream, line)
            except Exception:
                error = "Scheduler subprocess output callback failed"
                on_line = None
                stop.set()

    async def consume(stream: StreamName, pipe: asyncio.StreamReader | None, tail: _Tail) -> None:
        nonlocal error
        try:
            await _drain(
                pipe, lambda line: emit(stream, tail, line), tail,
                dataset_get=dataset_get, stream_name=stream,
            )
        except Exception:
            error = error or "Failed to read scheduler subprocess output"
            stop.set()

    stopper = asyncio.create_task(stop.wait())
    done = asyncio.gather(
        process.wait(),
        consume("stdout", process.stdout, stdout),
        consume("stderr", process.stderr, stderr),
        return_exceptions=True,
    )
    try:
        if on_process_started is not None:
            try:
                on_process_started(process)
            except Exception:
                error = "Scheduler subprocess start callback failed"
                stop.set()
        await asyncio.wait((done, stopper), return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set() and not done.done():
            _signal(process, force=False)
            await asyncio.wait((done,), timeout=_TERMINATE_GRACE_S)
            if not done.done():
                _signal(process, force=True)
                await asyncio.wait((done,), timeout=_TERMINATE_GRACE_S)
                if not done.done():
                    error = "Subprocess cleanup unconfirmed"
                    logging.error(error)
                    close_subprocess_pipes(process)
                    done.cancel()
        results = await asyncio.gather(done, return_exceptions=True)
        if isinstance(results[0], BaseException) or any(
            isinstance(item, BaseException) for item in results[0]
        ):
            error = error or "Failed to read or reap scheduler subprocess"
    finally:
        stopper.cancel()
        try:
            if on_process_ended is not None:
                on_process_ended()
        except Exception:
            error = error or "Scheduler subprocess end callback failed"
        await asyncio.gather(stopper, return_exceptions=True)
    return SchedulerCLIResult(
        process.returncode, error=error,
        stdout_truncated=stdout.truncated, stderr_truncated=stderr.truncated,
        stdout=stdout.text(), stderr=stderr.text(),
    )


async def run_scheduler_cli(
    args: Sequence[str],
    data_dir: Path,
    *,
    timeout_s: float,
    run_cmd: str,
    on_line: LineCallback | None,
    on_process_started: Callable[[asyncio.subprocess.Process], None] | None,
    on_process_ended: Callable[[], None] | None,
) -> SchedulerCLIResult:
    """Run a CLI action; stream redacted lines (no terminators) before tail eviction.

    The deadline starts before spawn. Timeout/cancellation wait for a raced
    spawn, then stop the child and bound the remaining drain/reap cleanup.
    Raw lines over 1 MiB are omitted rather than exposing partial secrets.
    """
    action_args = tuple(args)
    if action_args[:1] == ("--datadir",):
        action_args = action_args[2:]  # Use only the server-resolved directory.
    stop = asyncio.Event()
    supervisor = asyncio.create_task(_supervise(
        action_args, data_dir, run_cmd, on_line, on_process_started,
        on_process_ended, stop,
    ))
    try:
        finished, _ = await asyncio.wait((supervisor,), timeout=timeout_s)
        if finished:
            return supervisor.result()
        stop.set()
        result = await asyncio.shield(supervisor)
        return replace(result, returncode=None, timed_out=True)
    except asyncio.CancelledError:
        stop.set()
        while not supervisor.done():
            try:
                await asyncio.shield(supervisor)
            except asyncio.CancelledError:
                continue  # Repeated cancellation must not interrupt cleanup.
        supervisor.result()
        raise
