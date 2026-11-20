import asyncio
from datetime import date, datetime, timezone
import json
import logging

import pytest

import td_scheduler_workflow
from td_const import OTBR_RESTAPI_DATASET_ACTIVE_FILENAME
from td_logging import format_event
from td_network_identity import NetworkScope
from td_scheduler import SchedulerSettings
from td_scheduler_workflow import RunnerResult, run_workflow
from util_data import write_network_scope


_NETWORK = "0123456789abcdef"
_SETTINGS = SchedulerSettings(ext_pan_id=_NETWORK)
_MONTHLY = date(2026, 11, 8)
_NOW = datetime(2026, 11, 8, 4, 20, tzinfo=timezone.utc)
_ACTIVE = "otbr-restapi --raw node dataset active get"
_PURGE = "health purge --apply --json"
_REPACK = "system database repack"
_FULL = (
    "source-probe --source otbr-cli --json",
    "otbr-cli thread-network-info",
    "otbr-cli meshdiag routerneighbortable",
    "otbr-cli meshdiag childtable",
    "otbr-cli meshdiag childip6",
    "otbr-cli networkdiag fetch-all",
    "otbr-cli networkdiag multicast-neighbors",
    "source-probe --source otbr-restapi --json",
    _ACTIVE,
    "otbr-restapi devices clear --yes",
    "otbr-restapi devices fetch",
    "otbr-restapi devices list",
    "otbr-restapi diagnostics fetch-all --items-only --no-update-devices --no-basic-fallback",
    "otbr-restapi diagnostics list",
    "otbr-restapi mesh-diagnostics fetch-all --routers-only --items-only --no-update-devices"
    " --preserve-diagnostics --no-fallback --diagnostic-response-fallback",
    "otbr-restapi actions list",
    "otbr-restapi download",
    "source-probe --source ha-matter-ws --json",
    "ha-matter-ws server-info",
    "ha-matter-ws devices list",
    "ha-matter-ws devices fetch-all",
    "ha-matter-ws thread border-routers",
    "ha-matter-ws thread diagnostics list",
    "ha-matter-ws diagnostics fetch-all",
    "ha-matter-ws mesh-diagnostics fetch-all",
    "ha-matter-ws network-topology",
    "ha-matter-ws topology",
    "ha-matter-ws dashboard",
    "ha-matter-ws all",
    "mdns thread --write-scope-snapshots",
    "process-eve",
    "merge-dataset",
    "unify-dataset --dataset otbr_cli_unified --network extpan:0123456789abcdef --allow-partial --json",
    "unify-dataset --dataset otbr_restapi_unified --network extpan:0123456789abcdef --allow-partial --json",
    "unify-dataset --dataset ha_matter_ws_unified --network extpan:0123456789abcdef --allow-partial --json",
    "unify-dataset --dataset mdns_unified --allow-partial --json",
    "unify-dataset --dataset multi_source_unified --network extpan:0123456789abcdef --allow-partial --json",
    "health process-dataset --dataset all --allow-partial",
    _PURGE,
)


def _records(caplog):
    decoder = json.JSONDecoder()
    parsed = []
    for record in caplog.records:
        if record.name != "td_scheduler_workflow":
            continue
        line = record.getMessage()
        fields = {}
        while line:
            key, _, remainder = line.partition("=")
            assert key not in fields
            fields[key], end = decoder.raw_decode(remainder)
            assert end == len(remainder) or remainder[end] == " "
            line = remainder[end:].lstrip()
        parsed.append((record.levelno, fields))
    return parsed


class _Fake:
    def __init__(self, path, *, outcomes=None, provenance="observed", network=_NETWORK):
        self.path = path
        self.outcomes = outcomes or {}
        self.provenance = provenance
        self.network = network
        self.argv = []
        self.runs = []
        self.timeouts = []
        self.progress = []

    async def runner(self, args, *, timeout_s, run_cmd, on_line):
        self.argv.append(args)
        self.runs.append(run_cmd)
        self.timeouts.append(timeout_s)
        command = " ".join(args)
        if command in self.outcomes:
            result = self.outcomes[command]
            if isinstance(result, Exception):
                raise result
            return result
        if command == _ACTIVE:
            path = self.path / OTBR_RESTAPI_DATASET_ACTIVE_FILENAME
            path.write_text("{}")
            write_network_scope(path, NetworkScope(
                self.network, None, self.provenance, None, _NOW.isoformat(), (),
            ))
        if command.startswith(_PURGE):
            on_line("stdout", json.dumps({
                "command": "purge", "dryRun": False, "deleted": {"observations": 7},
            }))
        return RunnerResult(0)

    def kwargs(self, **overrides):
        return dict(dict(
            job_id="test-run", settings=_SETTINGS, data_dir=self.path, slot=None,
            quick=False, runner=self.runner, progress=self.progress.append,
            locks=(), clock=lambda: _NOW,
        ), **overrides)

    def run(self, **overrides):
        return asyncio.run(run_workflow(**self.kwargs(**overrides)))


def _reconcile(records, summary, fake):
    by_event = lambda name: [record for _, record in records if record["event"] == name]
    start, = by_event("run_start")
    footer, = by_event("run_end")
    paired_start = by_event("command_start")
    paired_end = by_event("command_end")
    assert [row["run_cmd"] for row in paired_start] == fake.runs
    assert [row["run_cmd"] for row in paired_end] == fake.runs
    assert len(set(fake.runs)) == len(fake.runs)
    for begin, end, argv in zip(paired_start, paired_end, fake.argv, strict=True):
        assert begin["argv"] == end["argv"] == ["--datadir", str(fake.path), *argv]
        assert begin["started_at"] <= end["finished_at"]
        assert end["timing_precision_s"] == 0.001
        assert end["timing_kind"] == "scheduler-process" and end["timing_unit"] == "s"
        assert end["duration_s"] >= 0
    skips = [*by_event("command_skip"), *by_event("stage_skip")]
    assert all("duration_s" not in skip and "exit" not in skip for skip in skips)
    assert footer["skip_count"] == len(skips)
    assert footer["command_count"] == len(fake.argv)
    assert footer["process_duration_s"] == round(sum(row["duration_s"] for row in paired_end), 3)
    assert footer["wall_duration_s"] >= footer["lock_wait_s"] >= 0
    assert footer["result_kind"] == "job"
    assert footer["run_id"] == start["run_id"] == summary["run_id"]
    assert footer["mode"] == start["mode"] == summary["mode"]
    assert footer["exit"] == summary["exit"]
    attempted_checks = by_event("check_end")
    assert len(by_event("check_start")) == len(attempted_checks)
    assert all("run_cmd" not in row and "argv" not in row for row in attempted_checks)
    assert summary["total_steps"] == len(fake.argv) + len(skips) + len(attempted_checks)
    assert summary["completed_steps"] == summary["total_steps"]


@pytest.mark.parametrize(("quick", "slot", "expected_mode"), [
    (False, _MONTHLY, "full"), (True, _MONTHLY, "full"),
    (False, date(2026, 11, 9), "full"), (True, None, "quick"),
])
def test_exact_inventory_budgets_and_evidence(tmp_path, caplog, quick, slot, expected_mode):
    caplog.set_level(logging.INFO, "td_scheduler_workflow")
    fake = _Fake(tmp_path)
    result = fake.run(quick=quick, slot=slot)
    expected = list(_FULL)
    budgets = [30 if command.startswith("source-probe") else 3600 for command in _FULL[:30]]
    budgets.extend([600] * 8 + [1800])
    if expected_mode == "quick":
        for index in (14, 12, 4, 3, 2):
            expected.pop(index)
            budgets.pop(index)
        expected[2] += " -cno"
    if slot == _MONTHLY:
        expected.append(_REPACK)
        budgets.append(1800)
    assert fake.argv == [cmd.split() for cmd in expected]
    assert fake.timeouts == budgets
    assert result["status"] == "done"
    assert result["mode"] == expected_mode
    assert result["keep_days"] == 10
    assert result["steps"]["health:purge"]["deleted"] == {"observations": 7}
    assert fake.progress[0]["phase"] == "waiting"
    assert fake.progress[-1] == result
    records = _records(caplog)
    _reconcile(records, result, fake)
    skips = [row for _, row in records if row["event"] == "command_skip"]
    assert sum(row["reason"] == "quick" for row in skips) == (5 if expected_mode == "quick" else 0)
    assert sum(row["reason"] == "monthly-not-due" for row in skips) == (slot != _MONTHLY)


@pytest.mark.parametrize(("failure", "exit_code", "step", "skip_reason"), [
    (_FULL[0], 1, "otbr-cli:probe", "source-unavailable"),
    (_FULL[7], 2, "otbr-restapi:probe", "preflight-error"),
    (_FULL[17], 1, "ha-matter-ws:probe", "source-unavailable"),
    (_ACTIVE, 1, "otbr-restapi:active-dataset", "active-dataset-failed"),
])
def test_preflight_or_active_failure_retains_other_sources_and_maintenance(
        tmp_path, caplog, failure, exit_code, step, skip_reason):
    caplog.set_level(logging.INFO, "td_scheduler_workflow")
    fake = _Fake(tmp_path, outcomes={failure: RunnerResult(exit_code)})
    result = fake.run(slot=_MONTHLY)
    assert result["status"] == "error"
    source = result["steps"][step]["source"]
    assert result["source_states"][source] == "failed"
    assert any(r["reason"] == skip_reason for r in result["steps"].values())
    assert fake.argv[-2:] == [_PURGE.split(), _REPACK.split()]
    for argv in fake.argv[fake.argv.index(failure.split()) + 1:]:
        assert argv[0] != source
    _reconcile(_records(caplog), result, fake)


@pytest.mark.parametrize(("provenance", "network", "reason"), [
    ("observed", "1123456789abcdef", "network-mismatch"),
    ("operator", _NETWORK, "identity-not-observed"),
    ("unknown", None, "identity-not-observed"),
    ("observed", "BAD", "invalid-sidecar"),
])
def test_rest_guard_rejects_nonmatching_or_invalid_scope(tmp_path, provenance, network, reason):
    fake = _Fake(tmp_path, provenance=provenance, network=network)
    result = fake.run()
    check = result["steps"]["otbr-restapi:identity"]
    assert (check["status"], check["reason"]) == ("failed", reason)
    assert not any(argv[0] == "otbr-restapi" and "--raw" not in argv for argv in fake.argv)
    assert result["status"] == "error"
    assert _PURGE.split() in fake.argv


@pytest.mark.parametrize(("index", "block_from"), [
    (1, None), (10, None), (30, None), (31, None),
    (32, 36), (33, 36), (34, 36), (35, 36),
    (36, 37), (37, 38), (38, 39),
])
def test_each_processing_gate_and_independent_failures(tmp_path, index, block_from):
    fake = _Fake(tmp_path, outcomes={_FULL[index]: RunnerResult(17)})
    result = fake.run(slot=_MONTHLY)
    expected = (*_FULL, _REPACK)[:block_from]
    assert fake.argv == [command.split() for command in expected]
    assert result["status"] == "error"
    assert len([r for r in result["steps"].values() if r.get("exit") == 17]) == 1
    skipped = [r for r in result["steps"].values() if r.get("reason") == "failed-dependency"]
    assert len(skipped) == 40 - len(expected)
    assert all(result["steps"][r["blocked_by"]]["status"] != "completed" for r in skipped)


def test_structured_outcome_before_tail_eviction_preserves_nested_values_and_severity(tmp_path, caplog):
    caplog.set_level(logging.INFO, "td_scheduler_workflow")
    fake = _Fake(tmp_path)

    async def runner(args, *, timeout_s, run_cmd, on_line):
        result = await fake.runner(args, timeout_s=timeout_s, run_cmd=run_cmd, on_line=on_line)
        if args == _FULL[5].split():
            on_line("stderr", "[2026-11-08 04:21:00,000] WARNING: " + format_event(
                "target_outcome", source="otbr-cli", command="networkdiag fetch-all", stage="child",
                run_cmd="child-local", coverage="partial", attempts=[{"case": "a b", "verified": True}],
            ))
            for phase, population in (("initial", 5), ("effective", 6)):
                on_line("stderr", format_event(
                    "outcome_summary", source="otbr-cli", command="networkdiag fetch-all",
                    stage="child", status_phase=phase, population=population, availability="available",
                ))
            on_line("stderr", 'prefix event="target_outcome"')
            on_line("stderr", 'event="target_outcome" event="duplicate"')
            for _ in range(70):
                on_line("stderr", "x" * 1024)
            return RunnerResult(0, stderr_truncated=True)
        return result

    result = fake.run(runner=runner, job_id="evidence-run")
    records = _records(caplog)
    target, = [(level, row) for level, row in records if row["event"] == "target_outcome"]
    level, row = target
    assert level == logging.WARNING
    assert row["run_id"] == "evidence-run"
    assert row["run_cmd"] == "evidence-run:cmd-6"
    assert row["stream"] == "stderr" and row["coverage"] == "partial"
    assert row["child_timestamp"] == "2026-11-08 04:21:00,000"
    assert row["attempts"] == [{"case": "a b", "verified": True}]
    assert [(r["status_phase"], r["population"]) for _, r in records
            if r["event"] == "outcome_summary"] == [("initial", 5), ("effective", 6)]
    assert len([r for _, r in records if r["event"] == "child_output" and r["malformed_record"]]) == 1
    step = result["steps"]["otbr-cli:networkdiag-fetch-all"]
    assert step["status"] == "completed" and step["stderr_truncated"]
    assert step["warning_lines"] == 1
    assert step["evidence_counts"] == {"target_outcome": 1, "outcome_summary": 2}
    assert step["coverage"] == [
        {"event": "outcome_summary", "stage": "child", "status_phase": phase,
         "population": count, "availability": "available"}
        for phase, count in (("initial", 5), ("effective", 6))
    ]


@pytest.mark.parametrize("repack", [True, False])
def test_manual_maintenance_has_no_collection_or_network_id(tmp_path, repack):
    fake = _Fake(tmp_path)
    result = fake.run(settings=SchedulerSettings(retention_override=14), maintenance_repack=repack)
    expected = [(_PURGE + " --keep-days 14").split()]
    if repack:
        expected.append(_REPACK.split())
    assert fake.argv == expected
    assert fake.timeouts == [1800] * len(expected)
    assert result["status"] == "done" and result["steps"]["health:purge"]["deleted"]


@pytest.mark.parametrize(("response", "outcome"), [
    (OSError("private command"), "error"),
    (RunnerResult(None, error="password=private"), "error"),
    (TimeoutError(), "timeout"),
    (RunnerResult(-15, timed_out=True), "timeout"),
])
def test_runner_errors_and_maintenance_timeout_are_terminal(tmp_path, caplog, response, outcome):
    caplog.set_level(logging.INFO, "td_scheduler_workflow")
    fake = _Fake(tmp_path, outcomes={_PURGE: response})
    result = fake.run(settings=SchedulerSettings(), maintenance_repack=True)
    step = result["steps"]["health:purge"]
    assert step["outcome"] == outcome and step["status"] == "failed"
    assert step["maintenance_unconfirmed"] == (outcome == "timeout")
    assert result["steps"]["system:repack"]["reason"] == "failed-dependency"
    assert "private" not in caplog.text
    _reconcile(_records(caplog), result, fake)


@pytest.mark.parametrize("waiting", [False, True])
def test_cancel_releases_reserved_locks_and_emits_complete_footer(tmp_path, caplog, waiting):
    caplog.set_level(logging.INFO, "td_scheduler_workflow")
    fake = _Fake(tmp_path)

    async def run():
        first, second = asyncio.Lock(), asyncio.Lock()
        entered = asyncio.Event()
        reaped = asyncio.Event()
        if waiting:
            await second.acquire()

        async def runner(args, *, timeout_s, run_cmd, on_line):
            assert first.locked() and second.locked()
            await fake.runner(args, timeout_s=timeout_s, run_cmd=run_cmd, on_line=on_line)
            entered.set()
            try:
                await asyncio.Future()
            finally:
                assert first.locked() and second.locked()
                reaped.set()

        task = asyncio.create_task(run_workflow(**fake.kwargs(
            runner=runner, locks=(first, second), maintenance_repack=True,
        )))
        if waiting:
            await asyncio.sleep(0)
            assert fake.progress[-1]["phase"] == "waiting"
            assert first.locked()
        else:
            await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not first.locked()
        assert second.locked() == waiting
        assert reaped.is_set() != waiting
        if waiting:
            second.release()

    asyncio.run(run())
    result = fake.progress[-1]
    assert result["status"] == "cancelled" and result["exit"] == 130
    assert result["steps"]["system:repack"]["reason"] == "cancelled"
    if waiting:
        assert not fake.argv
        assert result["steps"]["health:purge"]["status"] == "skipped"
    else:
        assert fake.argv == [_PURGE.split()]
        assert result["steps"]["health:purge"]["maintenance_unconfirmed"]
        assert result["steps"]["health:purge"]["exit"] is None
    _reconcile(_records(caplog), result, fake)


def test_process_sum_does_not_count_lock_wait(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.INFO, "td_scheduler_workflow")
    fake = _Fake(tmp_path)
    elapsed = 0.0
    monkeypatch.setattr(td_scheduler_workflow, "monotonic", lambda: elapsed)

    async def run():
        nonlocal elapsed
        lock = asyncio.Lock()
        await lock.acquire()

        async def runner(args, **kwargs):
            nonlocal elapsed
            elapsed += 1.234
            return await fake.runner(args, **kwargs)

        task = asyncio.create_task(run_workflow(**fake.kwargs(
            runner=runner, locks=[lock], maintenance_repack=False,
        )))
        await asyncio.sleep(0)
        assert not fake.argv
        elapsed += 5.678
        lock.release()
        return await task

    result = asyncio.run(run())
    assert result["wall_duration_s"] == 6.912
    assert result["lock_wait_s"] == 5.678
    assert result["process_duration_s"] == 1.234
    _reconcile(_records(caplog), result, fake)
