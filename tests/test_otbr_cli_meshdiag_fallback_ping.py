from __future__ import annotations

from types import SimpleNamespace
import logging

import pytest

import otbr_cli_device
import otbr_cli_meshdiag_childip6 as childip6
import otbr_cli_meshdiag_childtable as childtable
import otbr_cli_meshdiag_routerneighbortable as neighbortable
from otbr_cli_util import (
    add_meshdiag_table_evidence,
    classify_meshdiag_table_response,
    collect_per_router,
    meshdiag_collection_outcome,
    meshdiag_outcome_view,
)


COLLECTORS = (
    (neighbortable, "fetch_meshdiag_router_neighbor_table_for_device", "router_neighbor_table", "meshdiag routerneighbortable"),
    (childtable, "fetch_meshdiag_child_table_for_device", "router_child_table", "meshdiag childtable"),
    (childip6, "fetch_meshdiag_child_ip6_for_device", "router_child_ip6_table", "meshdiag childip6"),
)


@pytest.mark.parametrize("status,ping_status,classification,response", [
    ("success", "not-attempted", "answered", "observed"),
    ("timeout", "reply", "not_provided", "observed"),
    ("timeout", "no-reply", "unanswered", "not_observed"),
    ("protocol-error", "reply", "unanswered", "observed"),
    ("future-status", "reply", "unanswered", "observed"),
    ("success", "no-reply", "answered", "observed"),
])
def test_common_cli_table_view_preserves_request_and_data_facts(
    status, ping_status, classification, response,
):
    from copy import deepcopy

    record = {
        "rloc16": "0x0400", "router_child_table": [],
        "table_attempt": {"status": status},
        "target_identity": {"rloc16": "0x0400"},
        "ping": {"status": ping_status, "attempted": ping_status != "not-attempted"},
    }
    original = deepcopy(record)
    view = meshdiag_outcome_view(record, "meshdiag childtable")
    assert view.table_class == classification
    assert view.response == response
    assert view.original_status == status
    assert view.recovery_state != "recovered"
    assert record == original
    if status == "success":
        assert view.initial_status == view.effective_status == "completed"
        assert view.coverage == "complete"
        assert view.response_evidence == "direct"
    elif status == "future-status":
        assert view.initial_status == "other"
        assert view.coverage == "unknown"
        assert view.attempts == ()
    else:
        assert view.initial_status == view.effective_status == "failed"
        assert view.coverage == ("absent" if classification == "not_provided" else "unknown")
    if classification == "not_provided":
        assert view.display_label == "Not provided"
        assert view.initial_status == "failed"
        assert len(view.attempts) == 1


@pytest.mark.parametrize("record", [
    None, "malformed", {"rloc16": "0x0400"}, {"table_attempt": []},
    {"table_attempt": {"status": 7}},
    {"table_attempt": {"status": []}}, {"table_attempt": {"status": {}}},
])
def test_common_cli_table_unknowns_do_not_invent_attempts(record):
    view = meshdiag_outcome_view(record, "meshdiag childtable")
    assert view.initial_status == "other"
    assert view.coverage == "unknown"
    assert view.attempts == ()


def test_common_cli_ambiguous_target_is_not_a_request_attempt():
    from otbr_cli_util import build_meshdiag_ambiguous_result

    record = build_meshdiag_ambiguous_result(
        rloc16="0x0400", router={"rloc16": "0x0400"}, device_label="Router",
        result_table_key="router_child_table", command="meshdiag childtable",
    )
    view = meshdiag_outcome_view(record, "meshdiag childtable")
    assert view.initial_status == view.effective_status == "skipped"
    assert view.original_status == "error"
    assert view.reason_code == "ambiguous_target"
    assert view.response == "unknown"
    assert view.coverage == "unknown"
    assert view.attempts == ()


def test_common_cli_failed_table_with_unproven_data_does_not_claim_absence():
    view = meshdiag_outcome_view(
        {"table_attempt": {"status": "timeout"}, "router_child_table": [{"child": "x"}]},
        "meshdiag childtable",
    )
    assert view.coverage == "unknown"


def _ping_result(*, category: str, received: int, output: str = "Done") -> SimpleNamespace:
    return SimpleNamespace(
        error_category=category,
        received=received,
        sent=2,
        loss=0.0 if received else 1.0,
        round_trip_summary_ms={"min": 1.0, "max": 1.0, "average": 1.0} if received else None,
        timeout_seconds=3,
        output=output,
    )


@pytest.mark.parametrize(("module", "function_name", "table_key", "command"), COLLECTORS)
def test_successful_meshdiag_table_has_no_fallback_ping(
    monkeypatch, module, function_name, table_key, command
) -> None:
    monkeypatch.setattr(module, "exec_ot_ctl", lambda _command: "Done")
    monkeypatch.setattr(otbr_cli_device, "ping_device", lambda _request: pytest.fail("unexpected ping"))

    result = getattr(module, function_name)(
        "0x0400", {"rloc16": "0x0400", "extaddr": "0011223344556677"}, {}
    )

    assert result[table_key] == []
    assert result["table_attempt"]["command"] == command
    assert result["table_attempt"]["status"] == "success"
    assert result["ping"] == {"status": "not-attempted", "attempted": False, "elapsed_ms": 0}


@pytest.mark.parametrize(("module", "function_name", "table_key", "command"), COLLECTORS)
def test_timeout_records_ping_reply_without_repairing_table_failure(
    monkeypatch, module, function_name, table_key, command
) -> None:
    monkeypatch.setattr(module, "exec_ot_ctl", lambda _command: "Error 6: ResponseTimeout\nDone")
    monkeypatch.setattr("otbr_cli_util.util_network.fetch_meshlocal_prefix", lambda: "fd00::/64")
    requests = []
    monkeypatch.setattr(
        otbr_cli_device,
        "ping_device",
        lambda request: requests.append(request) or _ping_result(category="none", received=2),
    )

    result = getattr(module, function_name)(
        "0x0400", {"rloc16": "0x0400", "extaddr": "0011223344556677"}, {}
    )

    assert result[table_key] == []
    assert result["_error"] == {"type": "ResponseTimeout"}
    assert result["table_attempt"]["command"] == command
    assert result["table_attempt"]["status"] == "timeout"
    assert result["ping"]["status"] == "reply"
    assert result["ping"]["attempted"] is True
    assert requests[0].count == 2
    assert requests[0].timeout_seconds == 3


def test_explicit_error_uses_ping_and_unsupported_is_separate_evidence(monkeypatch) -> None:
    monkeypatch.setattr("otbr_cli_util.util_network.fetch_meshlocal_prefix", lambda: "fd00::/64")
    record = {"rloc16": "0x0400", "router_child_table": []}

    result = add_meshdiag_table_evidence(
        record,
        command="meshdiag childtable",
        table_status="error",
        error_type="Unsupported",
        elapsed_ms=4,
        router={"extaddr": "0011223344556677"},
        device_label="Router",
        ping=lambda _request: _ping_result(
            category="local-dispatch", received=0, output="Error: unsupported"
        ),
    )

    assert result["_error"] == {"type": "Unsupported"}
    assert result["ping"]["status"] == "unsupported"
    assert result["ping"]["attempted"] is True


def test_unreachable_and_unavailable_targets_remain_explicit_failures(monkeypatch) -> None:
    monkeypatch.setattr("otbr_cli_util.util_network.fetch_meshlocal_prefix", lambda: "fd00::/64")
    unreachable = add_meshdiag_table_evidence(
        {"rloc16": "0x0400", "router_child_table": []},
        command="meshdiag childtable",
        table_status="timeout",
        error_type="ResponseTimeout",
        elapsed_ms=4,
        router={"extaddr": "0011223344556677"},
        device_label="Router",
        ping=lambda _request: _ping_result(category="timeout", received=0),
    )
    unavailable = add_meshdiag_table_evidence(
        {"rloc16": "0x0401", "router_child_table": []},
        command="meshdiag childtable",
        table_status="error",
        error_type="NoRoute",
        elapsed_ms=4,
        router={"extaddr": "0011223344556677"},
        device_label="Child",
        ping=lambda _request: pytest.fail("unexpected ping"),
    )

    assert unreachable["_error"] == {"type": "ResponseTimeout"}
    assert unreachable["ping"]["status"] == "no-reply"
    assert unavailable["_error"] == {"type": "NoRoute"}
    assert unavailable["ping"] == {"status": "unavailable", "attempted": False, "elapsed_ms": 0}


def test_protocol_error_does_not_ping_and_all_failed_outcome_is_not_usable() -> None:
    status, error_type = classify_meshdiag_table_response("incomplete response")
    result = add_meshdiag_table_evidence(
        {"rloc16": "0x0400", "router_child_table": []},
        command="meshdiag childtable",
        table_status=status,
        error_type=error_type,
        elapsed_ms=1,
        router={"extaddr": "0011223344556677"},
        device_label="Router",
        ping=lambda _request: pytest.fail("unexpected ping"),
    )

    assert result["_error"] == {"type": "ProtocolError"}
    assert result["ping"]["status"] == "not-attempted"
    assert meshdiag_collection_outcome([result]).has_usable_data is False


def test_mixed_table_outcome_is_partial_even_when_failure_ping_replies() -> None:
    outcome = meshdiag_collection_outcome([
        {"table_attempt": {"status": "success"}},
        {"table_attempt": {"status": "timeout"}, "ping": {"status": "reply"}},
    ])

    assert outcome.status.value == "partial"
    assert outcome.has_usable_data is True


def test_collect_per_router_deduplicates_identical_and_marks_conflicting_identities() -> None:
    calls = []
    ambiguous = []
    results = collect_per_router(
        router_table_data=[
            {"rloc16": "0x0400", "extaddr": "0011223344556677"},
            {"rloc16": "0x0400", "extaddr": "0011223344556677"},
            {"rloc16": "0x0800", "extaddr": "8899aabbccddeeff"},
            {"rloc16": "0x0800", "extaddr": "0011223344556677"},
        ],
        collect_fn=lambda rloc16, router, _map: calls.append((rloc16, router)) or {"rloc16": rloc16},
        collection_name="test",
        ambiguous_result_fn=lambda rloc16, router: ambiguous.append((rloc16, router)) or {"rloc16": rloc16, "_error": {"type": "AmbiguousTarget"}},
    )

    assert [call[0] for call in calls] == ["0x0400"]
    assert [item[0] for item in ambiguous] == ["0x0800"]
    assert [item["rloc16"] for item in results] == ["0x0400", "0x0800"]


def test_router_progress_has_fixed_deduplicated_population(monkeypatch, caplog):
    import otbr_cli_util

    ticks = iter([1.0, 1.25, 2.0, 2.5])
    monkeypatch.setattr(otbr_cli_util.time, "monotonic", lambda: next(ticks))
    caplog.set_level(logging.INFO)
    callbacks = []
    records = collect_per_router(
        [
            {"rloc16": "0x0400", "extaddr": "0011223344556677"},
            {"rloc16": "0x0400", "extaddr": "0011223344556677"},
            {"rloc16": "0x0800", "extaddr": "0011223344556677"},
            {"rloc16": "0x0800", "extaddr": "8899aabbccddeeff"},
            {"rloc16": "bad"}, None,
        ],
        lambda rloc, *_args: {"rloc16": rloc, "table_attempt": {"status": "success"}},
        collection_name="meshdiag childtable",
        ambiguous_result_fn=lambda rloc, _router: {
            "rloc16": rloc, "table_attempt": {"status": "ambiguous"}, "_error": {},
        },
        on_result=lambda *args: callbacks.append(len(args[0])),
    )
    progress = [
        record.getMessage() for record in caplog.records
        if 'event="target_progress"' in record.getMessage()
    ]
    assert len(records) == 2
    assert callbacks == [1, 2]
    assert len(progress) == 2
    assert 'progress="[1/2]"' in progress[0]
    assert 'status="answered"' in progress[0]
    assert 'elapsed_s=0.25' in progress[0]
    assert 'progress="[2/2]"' in progress[1]
    assert 'status="unanswered"' in progress[1]
    assert 'elapsed_s=0.5' in progress[1]
    assert "rejected=2" in caplog.text


def test_empty_router_stage_has_no_fictitious_progress(caplog):
    caplog.set_level(logging.INFO)
    assert collect_per_router([], lambda *_args: pytest.fail("unexpected request")) == []
    assert "targets=0" in caplog.text
    assert 'event="target_progress"' not in caplog.text


def test_mesh_summary_preserves_legacy_and_ping_table_distinction(caplog):
    from otbr_cli_util import log_meshdiag_summary

    caplog.set_level(logging.INFO)
    log_meshdiag_summary([
        {"table_attempt": {"status": "success"}},
        {"table_attempt": {"status": "timeout"}, "ping": {"status": "reply"},
         "target_identity": {"rloc16": "0x0400"}},
        {"table_attempt": {"status": "timeout"}},
        {"rloc16": "0x0800"},
    ], "meshdiag childtable", "retained_previous")
    assert "answered=1" in caplog.text
    assert "not_provided=1" in caplog.text
    assert "unanswered=1" in caplog.text
    assert "legacy=1" in caplog.text
    assert "guard_passed=true" in caplog.text


def test_mesh_final_scope_failure_is_not_saved(monkeypatch, tmp_path, caplog):
    import util_data

    monkeypatch.setattr(childtable, "fetch_and_parse_router_table", lambda *_args: [])
    monkeypatch.setattr(
        util_data, "write_network_scope",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("scope companion failed")),
    )
    caplog.set_level(logging.INFO)
    path = tmp_path / "td-otbr-cli-meshdiag-childtables.json"
    with pytest.raises(OSError, match="scope companion"):
        childtable.fetch_all_meshdiag_child_tables({}, output_path=path)
    assert path.exists()
    assert 'disposition="failed"' in caplog.text
    assert 'final="failed"' in caplog.text
    assert 'disposition="saved"' not in caplog.text


@pytest.mark.parametrize(
    "module,collector", [
        (childtable, "fetch_all_meshdiag_child_tables"),
        (childip6, "fetch_all_meshdiag_child_ip6_tables"),
        (neighbortable, "fetch_all_meshdiag_router_neighbor_tables"),
    ],
)
@pytest.mark.parametrize("written", [False, True])
def test_mesh_summary_uses_actual_writer_result(monkeypatch, tmp_path, caplog, module, collector, written):
    monkeypatch.setattr(module, "fetch_and_parse_router_table", lambda *_args: [])
    monkeypatch.setattr(module, "save_final_json", lambda *_args, **_kwargs: written)
    caplog.set_level(logging.INFO)
    getattr(module, collector)({}, output_path=tmp_path / "table.json")
    disposition = "saved" if written else "retained_previous"
    assert f'disposition="{disposition}"' in caplog.text
    assert f'final="{disposition}"' in caplog.text
    assert "answered=0" in caplog.text
    assert "legacy=0" in caplog.text
    assert "guard_passed=false" in caplog.text


@pytest.mark.parametrize("module,_function,_key,_command", COLLECTORS)
def test_mesh_checkpoint_reports_skip_and_failure(monkeypatch, tmp_path, caplog, module, _function, _key, _command):
    caplog.set_level(logging.INFO)
    module._write_checkpoint_best_effort([], tmp_path / "partial.json")
    assert 'disposition="skipped_unusable"' in caplog.text
    monkeypatch.setattr(module, "save_checkpoint_json", lambda *_a, **_k: (_ for _ in ()).throw(OSError("PSKc: SENTINEL")))
    module._write_checkpoint_best_effort(
        [], tmp_path / "networkKey=PATH_SENTINEL\npartial.json"
    )
    assert 'disposition="failed"' in caplog.text
    assert "SENTINEL" not in caplog.text