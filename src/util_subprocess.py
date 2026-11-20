"""Helpers for abandoning subprocess pipes after bounded cleanup."""

import asyncio
import os
import signal


def signal_subprocess(process: asyncio.subprocess.Process, *, force: bool) -> None:
    try:
        pid = getattr(process, "pid", None)
        if os.name == "posix" and isinstance(pid, int):
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
        elif process.returncode is None:
            process.kill() if force else process.terminate()
    except ProcessLookupError:
        pass


def close_subprocess_pipes(process: asyncio.subprocess.Process) -> None:
    # asyncio exposes pipe transports only through the process transport.
    transport = getattr(process, "_transport", None)
    if transport is not None:
        for descriptor in (1, 2):
            pipe = transport.get_pipe_transport(descriptor)
            if pipe is not None:
                pipe.close()

