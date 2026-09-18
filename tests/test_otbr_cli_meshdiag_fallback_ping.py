from __future__ import annotations

from types import SimpleNamespace

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
)


COLLECTORS = (
    (neighbortable, "fetch_meshdiag_router_neighbor_table_for_device", "router_neighbor_table", "meshdiag routerneighbortable"),
    (childtable, "fetch_meshdiag_child_table_for_device", "router_child_table", "meshdiag childtable"),
    (childip6, "fetch_meshdiag_child_ip6_for_device", "router_child_ip6_table", "meshdiag childip6"),
)


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