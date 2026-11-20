import asyncio
from pathlib import Path
import sys

import pytest

import td_scheduler_process as scheduler_process
from td_scheduler_process import run_scheduler_cli


_DATA_DIR = Path("resolved-data")
_DATASET_ARGS = ["otbr-restapi", "--raw", "node", "dataset", "active", "get"]


def _run(*, args=("health", "purge", "--apply", "--json"), timeout_s=5, **callbacks):
    return run_scheduler_cli(
        args, _DATA_DIR, timeout_s=timeout_s, run_cmd="job-1:cmd-2",
        on_line=callbacks.get("on_line"),
        on_process_started=callbacks.get("on_process_started"),
        on_process_ended=callbacks.get("on_process_ended"),
    )


class _Process:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = None
        self.releasing_wait = asyncio.Event()
        self.waiting = asyncio.Event()
        self.signals = []

    def finish(self, returncode):
        self.returncode = returncode
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.releasing_wait.set()

    async def wait(self):
        self.waiting.set()
        await self.releasing_wait.wait()
        return self.returncode

    def terminate(self):
        self.signals.append("terminate")

    def kill(self):
        self.signals.append("kill")
        self.finish(-9)


def test_streams_before_exit_and_keeps_structured_evidence_outside_tail(monkeypatch):
    async def exercise():
        process = _Process()
        received = []
        milestones = []
        stdout_started, stderr_started = asyncio.Event(), asyncio.Event()
        args = ["health", "purge", "--apply", "--json"]

        async def spawn(*argv, **kw):
            assert argv[:2] == (sys.executable, str(Path(scheduler_process.__file__).with_name("td_cli.py")))
            assert argv[2:] == ("--datadir", str(_DATA_DIR), *args)
            assert kw["stdin"] == asyncio.subprocess.DEVNULL
            assert kw["stdout"] == kw["stderr"] == asyncio.subprocess.PIPE
            assert kw["env"]["TD_RUN_CMD"] == "job-1:cmd-2"
            assert kw["env"]["PYTHONUNBUFFERED"] == "1"
            return process

        def line(stream, text):
            assert milestones == [process]
            received.append((stream, text))
            (stdout_started if stream == "stdout" else stderr_started).set()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(_run(
            args=args, on_line=line, on_process_started=milestones.append,
            on_process_ended=lambda: milestones.append("ended"),
        ))
        await process.waiting.wait()
        process.stdout.feed_data(b'networkKey="split')
        # A complete stderr record arrives while stdout is still mid-line.
        event = '[2026-11-19 00:00:00,000] INFO: event="outcome_summary" run_cmd="job-1:cmd-2" population=3'
        process.stderr.feed_data((event + "\n").encode())
        await stderr_started.wait()
        assert not stdout_started.is_set()
        process.stdout.feed_data(b' secret" value=9\r\n')
        await stdout_started.wait()
        assert received == [("stderr", event), ("stdout", 'networkKey="[Redacted]" value=9')]
        process.stdout.feed_data((("α" * 1000 + "\n") * 40 + "last stdout").encode())
        process.stderr.feed_data((("x" * 2000 + "\n") * 40 + "last stderr").encode())
        process.finish(17)
        result = await task
        assert result.returncode == 17 and not result.timed_out and result.error is None
        assert result.stdout_truncated and result.stderr_truncated
        assert len(result.stdout.encode()) <= 64 * 1024
        assert len(result.stderr.encode()) <= 64 * 1024
        assert result.stdout.endswith("last stdout\n") and result.stderr.endswith("last stderr\n")
        assert event not in result.stderr and ("stderr", event) in received
        assert "split secret" not in repr(received) + repr(result)
        assert milestones == [process, "ended"]

    asyncio.run(asyncio.wait_for(exercise(), 5))


@pytest.mark.parametrize("body", [
    b"00112233445566778899aabbccddeeff\nOutput written to stdout\n",
    b'{\n    "ActiveDataset": "00112233445566778899aabbccddeeff"\n}\nOutput written to stdout\n',
    b'"00112233445566778899aabbccddeeff"\nOutput written to stdout\n',
])
def test_raw_rest_dataset_stdout_never_exposes_unlabeled_tlv(monkeypatch, body):
    async def exercise():
        process = _Process()
        lines = []
        event = 'event="write" disposition="not_requested"'

        async def spawn(*argv, **kw):
            process.stdout.feed_data(body)
            process.stderr.feed_data(
                b'[2026-11-19] DEBUG: HTTP Response body: {"Tlvs":"00112233445566778899aabbccddeeff"}\n'
                + event.encode() + b"\n"
            )
            process.finish(0)
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        result = await _run(args=_DATASET_ARGS, on_line=lambda *item: lines.append(item))
        assert result.returncode == 0
        assert "00112233445566778899aabbccddeeff" not in repr(lines) + repr(result)
        assert ("stdout", "[Redacted active dataset output]") in lines
        assert ("stderr", event) in lines

    asyncio.run(asyncio.wait_for(exercise(), 5))


def test_dataset_normal_save_preserves_count_not_path(monkeypatch):
    async def exercise():
        process = _Process()

        async def spawn(*argv, **kw):
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(_run(args=_DATASET_ARGS))
        await process.waiting.wait()
        process.stdout.feed_data(b"Saved 3 rec")
        await asyncio.sleep(0)
        process.stdout.feed_data(b"ords to /private/cache.json\n")
        process.finish(0)
        assert (await task).stdout == "Saved 3 records to active dataset cache\n"

    asyncio.run(asyncio.wait_for(exercise(), 5))


def test_oversized_raw_line_is_omitted_as_a_unit(monkeypatch):
    async def exercise():
        process = _Process()
        lines = []

        async def spawn(*argv, **kw):
            process.stderr.feed_data(b"token=" + b"x" * 90 + b"\nnext\n")
            process.finish(0)
            return process

        monkeypatch.setattr(scheduler_process, "_MAX_LINE_BYTES", 64)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        result = await _run(on_line=lambda *item: lines.append(item))
        assert result.stderr_truncated
        assert lines == [("stderr", "[Omitted oversized subprocess line]"), ("stderr", "next")]

    asyncio.run(asyncio.wait_for(exercise(), 5))


@pytest.mark.parametrize("phase", ["spawn", "stream", "reap"])
def test_cancellation_waits_for_spawn_pipe_drain_and_reap(monkeypatch, phase):
    async def exercise():
        process = _Process()
        spawn_entered, release_spawn = asyncio.Event(), asyncio.Event()
        calls = []

        async def spawn(*argv, **kw):
            spawn_entered.set()
            await release_spawn.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(scheduler_process, "_TERMINATE_GRACE_S", 0)
        task = asyncio.create_task(_run(
            on_line=lambda *item: calls.append(item),
            on_process_started=lambda _: calls.append("started"),
            on_process_ended=lambda: calls.append("ended"),
        ))
        await spawn_entered.wait()
        process.stderr.feed_data(b"last stderr record")
        if phase != "spawn":
            release_spawn.set()
            await process.waiting.wait()
        if phase == "reap":
            # OS exit and pipe EOF can precede completion of the reap await.
            process.returncode = 0
            process.stdout.feed_eof()
            process.stderr.feed_eof()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert "ended" not in calls
        release_spawn.set()
        if phase == "reap":
            process.releasing_wait.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.signals == ([] if phase == "reap" else ["terminate", "kill"])
        assert calls == ["started", ("stderr", "last stderr record"), "ended"]

    asyncio.run(asyncio.wait_for(exercise(), 5))


def test_timeout_kills_reaps_and_keeps_redacted_tail(monkeypatch):
    async def exercise():
        process = _Process()
        ended = []

        async def spawn(*argv, **kw):
            process.stdout.feed_data(b"token=synthetic-secret")
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(scheduler_process, "_TERMINATE_GRACE_S", 0)
        result = await _run(timeout_s=0, on_process_ended=lambda: ended.append(process.returncode))
        assert result.timed_out and result.returncode is None and result.error is None
        assert result.stdout == 'token="[Redacted]"\n'
        assert process.signals == ["terminate", "kill"] and ended == [-9]

    asyncio.run(asyncio.wait_for(exercise(), 5))


def test_timeout_bounds_cleanup_when_child_exits_without_pipe_eof(monkeypatch):
    async def exercise():
        process = _Process()
        process.returncode = 0
        process.releasing_wait.set()

        async def spawn(*argv, **kw):
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(scheduler_process, "_TERMINATE_GRACE_S", 0.01)
        result = await asyncio.wait_for(_run(timeout_s=0.01), 0.5)
        assert result.timed_out
        assert result.error == "Subprocess cleanup unconfirmed"

    asyncio.run(exercise())


def test_launch_failure_never_exports_exception_contents(monkeypatch):
    async def exercise():
        async def spawn(*argv, **kw):
            raise OSError("raw subprocess argument or secret env contents")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        calls = []
        result = await _run(on_process_started=calls.append, on_process_ended=lambda: calls.append("ended"))
        assert result.returncode is None and not result.timed_out
        assert result.error == "Failed to start scheduler subprocess"
        assert calls == []

    asyncio.run(asyncio.wait_for(exercise(), 5))
