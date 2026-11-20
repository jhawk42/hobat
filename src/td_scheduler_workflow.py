"""Ordered scheduler workflow and correlated evidence; no subprocess ownership."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import re
from time import monotonic
from typing import Protocol

from td_collection_outcomes import STATUSES
from td_const import OTBR_RESTAPI_DATASET_ACTIVE_FILENAME, TD_DATA_DIR_ARG
from td_logging import format_event, redact_command_args, redact_sensitive_text
from td_network_identity import canonical_ext_pan_id
from td_scheduler import SchedulerSettings, is_second_sunday
from util_data import read_network_scope

_LOG = logging.getLogger(__name__)
_REVISION = 1
_TAIL_BYTES = 64 * 1024
_BUDGET = {"probe": 30, "collection": 3600, "processing": 600, "maintenance": 1800}
_TIMING = {"timing_kind": "scheduler-process", "timing_unit": "s", "timing_precision_s": 0.001}


@dataclass(frozen=True)
class RunnerResult:
    returncode: int | None
    timed_out: bool = False
    error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class Runner(Protocol):
    def __call__(
        self, args: list[str], *, timeout_s: int, run_cmd: str,
        on_line: Callable[[str, str], None],
    ) -> Awaitable[RunnerResult]: ...


@dataclass(frozen=True)
class _Step:
    id: str
    source: str
    command: str
    stage: str
    args: tuple[str, ...] = ()
    quick_skip: bool = False

    def identity(self) -> dict:
        return dict(step_id=self.id, source=self.source, command=self.command, stage=self.stage)


def _collect(source: str, *args: str, quick_skip: bool = False) -> _Step:
    command = tuple(arg for arg in args if not arg.startswith("-"))
    return _Step(f"{source}:{'-'.join(command)}", source, " ".join(command),
                 "collection", (source, *args), quick_skip)


def _probe(source: str) -> _Step:
    return _Step(f"{source}:probe", source, "source-probe", "probe",
                 ("source-probe", "--source", source, "--json"))


_REST_ACTIVE = _Step("otbr-restapi:active-dataset", "otbr-restapi", "node dataset active get",
                     "collection", ("otbr-restapi", "--raw", "node", "dataset", "active", "get"))
_REST_CHECK = _Step("otbr-restapi:identity", "otbr-restapi", "network-identity", "check")
_CLI_FETCH = _collect("otbr-cli", "networkdiag", "fetch-all")
_SOURCE_UNIFIED = ("otbr_cli_unified", "otbr_restapi_unified", "ha_matter_ws_unified", "mdns_unified")
_MULTI_UNIFIED = "multi_source_unified"
_HEALTH = _Step("health:process-all", "health", "process-dataset", "processing",
                ("health", "process-dataset", "--dataset", "all", "--allow-partial"))
_REPACK = _Step("system:repack", "system", "database repack", "maintenance",
                ("system", "database", "repack"))
_PURGE_ID = "health:purge"
_COLLECTION = (
    _probe("otbr-cli"),
    _collect("otbr-cli", "thread-network-info"),
    _collect("otbr-cli", "meshdiag", "routerneighbortable", quick_skip=True),
    _collect("otbr-cli", "meshdiag", "childtable", quick_skip=True),
    _collect("otbr-cli", "meshdiag", "childip6", quick_skip=True),
    _CLI_FETCH,
    _collect("otbr-cli", "networkdiag", "multicast-neighbors"),
    _probe("otbr-restapi"), _REST_ACTIVE, _REST_CHECK,
    _collect("otbr-restapi", "devices", "clear", "--yes"),
    _collect("otbr-restapi", "devices", "fetch"),
    _collect("otbr-restapi", "devices", "list"),
    _collect("otbr-restapi", "diagnostics", "fetch-all", "--items-only",
             "--no-update-devices", "--no-basic-fallback", quick_skip=True),
    _collect("otbr-restapi", "diagnostics", "list"),
    _collect("otbr-restapi", "mesh-diagnostics", "fetch-all", "--routers-only",
             "--items-only", "--no-update-devices", "--preserve-diagnostics", "--no-fallback",
             "--diagnostic-response-fallback", quick_skip=True),
    _collect("otbr-restapi", "actions", "list"),
    _collect("otbr-restapi", "download"),
    _probe("ha-matter-ws"),
    *(_collect("ha-matter-ws", *command.split()) for command in (
        "server-info", "devices list", "devices fetch-all", "thread border-routers",
        "thread diagnostics list", "diagnostics fetch-all", "mesh-diagnostics fetch-all",
        "network-topology", "topology", "dashboard", "all",
    )),
    _Step("mdns:thread", "mdns", "thread", "collection",
          ("mdns", "thread", "--write-scope-snapshots")),
    _Step("process-eve", "process-eve", "process-eve", "processing", ("process-eve",)),
    _Step("merge-dataset", "merge-dataset", "merge-dataset", "processing", ("merge-dataset",)),
)


def _steps(settings: SchedulerSettings, maintenance: bool) -> tuple[_Step, ...]:
    purge = _Step(_PURGE_ID, "health", "purge", "maintenance", settings.purge_args())
    if maintenance:
        return purge, _REPACK
    network = f"extpan:{canonical_ext_pan_id(settings.ext_pan_id)}"
    unified = tuple(
        _Step(dataset, "unify-dataset", dataset, "processing",
              ("unify-dataset", "--dataset", dataset,
               *(("--network", network) if dataset != "mdns_unified" else ()),
               "--allow-partial", "--json"))
        for dataset in (*_SOURCE_UNIFIED, _MULTI_UNIFIED)
    )
    return (*_COLLECTION, *unified, _HEALTH, purge, _REPACK)


def _identity_reason(data_dir: Path, expected: str | None) -> str | None:
    scope, reason = read_network_scope(data_dir / OTBR_RESTAPI_DATASET_ACTIVE_FILENAME)
    if scope is None:
        return reason or "invalid-scope"
    if scope["provenance"] != "observed":
        return "identity-not-observed"
    if scope["extPanId"] != canonical_ext_pan_id(expected):
        return "network-mismatch"
    return None


_PREFIX = re.compile(
    r"^(?:\[(?P<timestamp>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})\]\s+)?"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+"
)
_FIELD = re.compile(r"([a-zA-Z_]\w*)=")
_JSON = json.JSONDecoder()
_WRAPPER_EVENTS = {
    "run_start", "run_end", "command_start", "command_end", "command_skip",
    "stage_skip", "check_start", "check_end", "child_output",
}
_EVIDENCE_EVENTS = {
    "collector_summary", "step_end", "target_outcome", "outcome_summary",
    "workflow_summary", "checkpoint", "write", "transport_end",
}
_COVERAGE_LIMIT = 32


def _child_fields(line: str) -> dict | None:
    if not line.startswith('event="'):
        return None
    fields = {}
    offset = 0
    while offset < len(line):
        match = _FIELD.match(line, offset)
        if not match or match[1] in fields:
            return None
        try:
            fields[match[1]], offset = _JSON.raw_decode(line, match.end())
        except (ValueError, RecursionError):
            return None
        if offset < len(line) and line[offset] != " ":
            return None
        while offset < len(line) and line[offset] == " ":
            offset += 1
    if not all(isinstance(fields.get(key), str) for key in ("event", "source", "command", "stage")):
        return None
    return fields if fields["event"] not in _WRAPPER_EVENTS else None


def _log(event: str, level: int = logging.INFO, /, **fields: object) -> None:
    _LOG.log(level, "%s", format_event(event, **fields))


def _coverage(event: str, fields: dict) -> dict | None:
    if event not in {"collector_summary", "outcome_summary"}:
        return None
    counts = {
        key: fields[key] for key in ("version", "population", "verified_attempts", "targets", "processed", "records")
        if type(fields.get(key)) is int and fields[key] >= 0
    }
    if isinstance(statuses := fields.get("terminal_statuses"), dict):
        counts["terminal_statuses"] = {
            key: statuses[key] for key in STATUSES
            if type(statuses.get(key)) is int and statuses[key] >= 0
        }
    for key, values in (
        ("availability", ("available", "unavailable")),
        ("status_phase", ("initial", "effective")),
        ("final", ("saved", "retained_previous", "not_requested", "failed")),
    ):
        if fields.get(key) in values:
            counts[key] = fields[key]
    stage = fields["stage"]
    if not counts or not re.fullmatch(r"[a-z0-9._-]{1,64}", stage):
        return None
    return dict(event=event, stage=stage, **counts)


class _CommandEvidence:
    def __init__(self, step: _Step, run_id: str, run_cmd: str):
        self.step = step
        self.correlation = dict(run_id=run_id, run_cmd=run_cmd)
        self.maintenance_stdout = bytearray()
        self.event_counts: Counter = Counter()
        self.level_counts: Counter = Counter()
        self.stream_sizes: Counter = Counter()
        self.coverage: list[dict] = []
        self.coverage_truncated = False

    def on_line(self, stream: str, line: str) -> None:
        if self.stream_sizes[stream] <= _TAIL_BYTES:
            self.stream_sizes[stream] += len(line.encode("utf-8")) + 1
        if self.step.id == _PURGE_ID and stream == "stdout":
            encoded = (line + "\n").encode("utf-8")[-_TAIL_BYTES:]
            overflow = len(self.maintenance_stdout) + len(encoded) - _TAIL_BYTES
            if overflow > 0:
                del self.maintenance_stdout[:overflow]
            self.maintenance_stdout.extend(encoded)
        prefix = _PREFIX.match(line)
        level_name = prefix["level"] if prefix else "INFO"
        body = line[prefix.end():] if prefix else line
        self.level_counts[level_name] += 1
        fields = _child_fields(body)
        if fields is None:
            record = format_event(
                "child_output", **self.step.identity(), **self.correlation,
                stream=stream, child_severity=level_name, malformed_record=body.startswith('event="'),
            )
            # The runner has already redacted this complete line; only escape it.
            _LOG.log(logging.getLevelName(level_name), "%s line=%s", record, json.dumps(line))
            return
        event = fields.pop("event")
        # Preserve source/command/stage from the child, never its correlation.
        fields.update(self.correlation, step_id=self.step.id, stream=stream, child_severity=level_name)
        if prefix and prefix["timestamp"] is not None:
            fields["child_timestamp"] = prefix["timestamp"]
        _log(event, logging.getLevelName(level_name), **fields)
        if event in _EVIDENCE_EVENTS:
            self.event_counts[event] += 1
        if (coverage := _coverage(event, fields)) is not None:
            if len(self.coverage) < _COVERAGE_LIMIT:
                self.coverage.append(coverage)
            else:
                self.coverage_truncated = True

    def purge_counts(self) -> dict[str, int] | None:
        for line in reversed(bytes(self.maintenance_stdout).splitlines()):
            try:
                document = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if (isinstance(document, dict) and document.get("command") == "purge"
                    and document.get("dryRun") is False
                    and isinstance(deleted := document.get("deleted"), dict)
                    and all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                            and type(count) is int
                            for key, count in deleted.items())):
                return deleted
        return None

    def truncated(self, stream: str) -> bool:
        return self.stream_sizes[stream] > _TAIL_BYTES


def _utc(clock: Callable[[], datetime]) -> str:
    return clock().astimezone(timezone.utc).isoformat()


class _Run:
    def __init__(self, job_id, settings, data_dir, slot, quick, runner, progress, clock,
                 maintenance_repack):
        self.settings = settings
        self.data_dir = Path(data_dir)
        self.runner = runner
        self.progress = progress
        self.clock = clock
        self.quick = quick and slot is None and maintenance_repack is None
        self.maintenance = maintenance_repack is not None
        self.repack_due = (maintenance_repack if self.maintenance
                           else slot is not None and is_second_sunday(slot))
        self.steps = _steps(settings, self.maintenance)
        self.results = {}
        self.commands = 0
        self.process_ms = 0
        self.blocked_sources = {}
        self.started = monotonic()
        self.lock_wait_s = None
        now = clock()
        # The scheduler timer normally passes a UTC clock; label runs in host-local time.
        local = now.astimezone()
        self.metadata = dict(
            run_id=job_id, workflow_revision=_REVISION,
            trigger="scheduled" if slot is not None else "manual",
            mode="quick" if self.quick else "maintenance" if self.maintenance else "full",
            started_at=now.astimezone(timezone.utc).isoformat(),
            local_date=local.date().isoformat(), local_time=local.time().isoformat(),
            timezone=local.tzname(), utc_offset=local.strftime("%z"),
            slot=slot.isoformat() if slot is not None else None, keep_days=settings.keep_days,
        )

    def snapshot(self, phase, step=None):
        return dict(
            phase=phase, step_id=step.id if step else None, source=step.source if step else None,
            completed_steps=len(self.results), total_steps=len(self.steps), steps=dict(self.results),
        )

    def publish(self, phase, step=None):
        self.progress(self.snapshot(phase, step))

    def run_event(self, event, **fields):
        _log(event, source="scheduler",
             command="health-maintenance" if self.maintenance else "scheduler-nightly",
             stage="run", **self.metadata, **fields)

    def skip(self, step, reason, *, blocked_by=None):
        result = dict(status="skipped", reason=reason)
        if blocked_by is not None:
            result["blocked_by"] = blocked_by
        identity = step.identity()
        self.results[step.id] = dict(identity, **result)
        _log("command_skip" if step.args else "stage_skip",
             **identity, run_id=self.metadata["run_id"], **result)

    def skip_reason(self, step):
        if step.source in self.blocked_sources:
            return self.blocked_sources[step.source]
        if self.quick and step.quick_skip:
            return "quick", None
        dependencies = ()
        if step.id == _MULTI_UNIFIED:
            dependencies = _SOURCE_UNIFIED
        elif step is _HEALTH:
            dependencies = (_MULTI_UNIFIED,)
        elif step.id == _PURGE_ID and not self.maintenance:
            dependencies = (_HEALTH.id,)
        elif step is _REPACK:
            if not self.repack_due:
                return ("not-requested" if self.maintenance else "monthly-not-due"), None
            dependencies = (_PURGE_ID,)
        for dependency in dependencies:
            if self.results[dependency]["status"] != "completed":
                return "failed-dependency", dependency
        return None, None

    def check_identity(self, step) -> None:
        identity = dict(step.identity(), run_id=self.metadata["run_id"])
        start = monotonic()
        _log("check_start", **identity, started_at=_utc(self.clock))
        try:
            reason = _identity_reason(self.data_dir, self.settings.ext_pan_id)
        except Exception:
            reason = "identity-check-error"
        result = dict(status="failed" if reason else "completed", reason=reason)
        self.results[step.id] = dict(step.identity(), **result)
        _log("check_end", **identity, **result, finished_at=_utc(self.clock),
             duration_s=round(monotonic() - start, 3), timing_kind="in-process")

    async def command(self, step) -> None:
        args = list(step.args)
        if self.quick and step is _CLI_FETCH:
            args.append("-cno")
        self.commands += 1
        run_id = self.metadata["run_id"]
        run_cmd = f"{run_id}:cmd-{self.commands}"
        evidence = _CommandEvidence(step, run_id, run_cmd)
        timeout_s = _BUDGET[step.stage]
        identity = dict(step.identity(), run_id=run_id, run_cmd=run_cmd,
                        argv=redact_command_args([TD_DATA_DIR_ARG, str(self.data_dir), *args]))
        _log("command_start", **identity, timeout_s=timeout_s, started_at=_utc(self.clock))
        started = monotonic()
        result = RunnerResult(None)
        cancelled = False
        try:
            result = await self.runner(args, timeout_s=timeout_s, run_cmd=run_cmd,
                                       on_line=evidence.on_line)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except TimeoutError:
            result = RunnerResult(None, timed_out=True)
        except Exception as exc:
            result = RunnerResult(None, error=type(exc).__name__)
        finally:
            elapsed_ms = round((monotonic() - started) * 1000)
            self.process_ms += elapsed_ms
            if cancelled:
                outcome, reason = "cancelled", "cancelled"
            elif result.timed_out:
                outcome, reason = "timeout", "timeout"
            elif result.error or result.returncode is None:
                outcome, reason = "error", "runner-error"
            elif step.stage == "probe" and result.returncode == 1:
                outcome, reason = "unavailable", "source-unavailable"
            elif result.returncode != 0:
                outcome, reason = "failed", "preflight-error" if step.stage == "probe" else "nonzero-exit"
            else:
                outcome, reason = "completed", None
            status = outcome if outcome in {"cancelled", "completed"} else "failed"
            fields = dict(
                status=status, outcome=outcome, reason=reason, exit=result.returncode,
                duration_s=elapsed_ms / 1000,
                stdout_truncated=result.stdout_truncated or evidence.truncated("stdout"),
                stderr_truncated=result.stderr_truncated or evidence.truncated("stderr"),
                evidence_counts=dict(evidence.event_counts), warning_lines=evidence.level_counts["WARNING"],
                error_lines=evidence.level_counts["ERROR"] + evidence.level_counts["CRITICAL"],
            )
            if step.stage == "maintenance":
                fields["maintenance_unconfirmed"] = outcome in {"cancelled", "timeout"}
            if step.id == _PURGE_ID and outcome == "completed":
                fields["deleted"] = evidence.purge_counts()
            self.results[step.id] = dict(step.identity(), run_cmd=run_cmd, **fields)
            diagnostic = redact_sensitive_text(result.error)[:512] if result.error else None
            _log("command_end", **identity, **fields, **_TIMING,
                 error=diagnostic, finished_at=_utc(self.clock))
            if evidence.coverage:
                self.results[step.id].update(
                    coverage=evidence.coverage, coverage_truncated=evidence.coverage_truncated,
                )

    async def execute(self, locks):
        self.run_event("run_start")
        terminal = "done"
        try:
            self.publish("waiting")
            async with AsyncExitStack() as reserve:
                for lock in locks:
                    await reserve.enter_async_context(lock)
                self.lock_wait_s = round(monotonic() - self.started, 3)
                for step in self.steps:
                    reason, dependency = self.skip_reason(step)
                    if reason is not None:
                        self.skip(step, reason, blocked_by=dependency)
                        continue
                    self.publish("running", step)
                    if step.args:
                        await self.command(step)
                    else:
                        self.check_identity(step)
                    result = self.results[step.id]
                    if result["status"] == "failed":
                        terminal = "error"
                        if step.stage == "probe":
                            reason = ("source-unavailable" if result["outcome"] == "unavailable"
                                      else "preflight-error")
                            self.blocked_sources[step.source] = reason, step.id
                        elif step is _REST_ACTIVE or step is _REST_CHECK:
                            self.blocked_sources[step.source] = (
                                "active-dataset-failed" if step is _REST_ACTIVE else "identity-unverified",
                                step.id,
                            )
        except asyncio.CancelledError:
            terminal = "cancelled"
            raise
        except Exception:
            terminal = "error"
            raise
        finally:
            if self.lock_wait_s is None:
                self.lock_wait_s = round(monotonic() - self.started, 3)
            for step in self.steps:
                if step.id not in self.results:
                    self.skip(step, "cancelled" if terminal == "cancelled" else "workflow-error")
            summary = self.finish(terminal)
        return summary

    def finish(self, status) -> dict:
        step_states = {key: result["status"] for key, result in self.results.items()}
        groups = {}
        for source in dict.fromkeys(step.source for step in self.steps):
            states = [step_states[step.id] for step in self.steps if step.source == source]
            groups[source] = next(state for state in ("cancelled", "failed", "completed", "skipped")
                                  if state in states)
        counts = Counter(step_states.values())
        fields = dict(
            status=status, exit={"done": 0, "error": 1, "cancelled": 130}[status],
            result_kind="job", finished_at=_utc(self.clock),
            wall_duration_s=round(monotonic() - self.started, 3), lock_wait_s=self.lock_wait_s,
            process_duration_s=self.process_ms / 1000, command_count=self.commands,
            skip_count=counts["skipped"], failure_count=counts["failed"],
            cancelled_count=counts["cancelled"],
            failed_command_count=sum(s["status"] == "failed" and "run_cmd" in s for s in self.results.values()),
            skipped_command_count=sum(bool(s.args) and step_states[s.id] == "skipped" for s in self.steps),
            source_states=groups, step_states=step_states,
        )
        self.run_event("run_end", **fields, **_TIMING)
        summary = dict(self.metadata, **fields, **self.snapshot(status))
        self.progress(summary)
        return summary


async def run_workflow(
    *, job_id: str, settings: SchedulerSettings, data_dir: Path, slot: date | None,
    quick: bool, runner: Runner, progress: Callable[[dict], None],
    locks: Iterable[asyncio.Lock], clock: Callable[[], datetime],
    maintenance_repack: bool | None = None,
) -> dict:
    """Run one chain under caller-ordered locks; runner receives td_cli action args.

    The runner supplies complete redacted lines and must reap before raising
    CancelledError. Terminal progress is published even when cancellation is
    propagated; no child output bodies are included in progress or result.
    """
    workflow = _Run(job_id, settings, data_dir, slot, quick, runner, progress, clock,
                    maintenance_repack)
    return await workflow.execute(locks)
