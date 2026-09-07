from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

import otbr_cli_networkdiag_topology as topology


def _target() -> topology.ChildFetchTarget:
    return topology.ChildFetchTarget(
        parent_rloc16="0x1000",
        child_rloc16="0x1001",
        child_record={"rloc16": "0x1001"},
    )


def test_child_fetch_policies_preserve_attempts_and_delays() -> None:
    fast, detail = topology.build_child_fetch_policies(True, True)

    assert fast.mode == "fast"
    assert fast.minimum_attempts == 2
    assert [attempt.detail_level for attempt in fast.attempts] == [1, 1]
    assert [attempt.delay_after_failure_s for attempt in fast.attempts] == [0.25, None]
    assert fast.stop_after_first_response is True

    assert detail.mode == "detail"
    assert detail.minimum_attempts == 3
    assert [attempt.detail_level for attempt in detail.attempts] == [1, 2, 3, 3, 4]
    assert [attempt.delay_after_failure_s for attempt in detail.attempts] == [0.25, 0.5, 0.75, 1.0, None]
    assert detail.stop_after_first_response is False
    assert all(attempt.tlv_values for attempt in (*fast.attempts, *detail.attempts))

    with pytest.raises(FrozenInstanceError):
        fast.mode = "detail"  # type: ignore[misc]
    with pytest.raises(ValueError, match="detail level"):
        topology.ChildFetchAttempt(0, 8, "0 1 2 8", None)
    with pytest.raises(ValueError, match="TLVs"):
        topology.ChildFetchAttempt(0, 1, "invalid", None)


def test_collect_child_targets_is_stable_deduplicated_and_non_mutating() -> None:
    topology_map = {
        "0x1000": {"children": [
            {"rloc16": "0x1001", "name": "first"},
            "bad",
            {},
            {"rloc16": "0x1002"},
        ]},
        "0x2000": {"children": [
            {"rloc16": "0X1001", "name": "duplicate"},
            {"rloc16": "0x2001"},
        ]},
    }

    targets = topology.collect_child_fetch_targets(
        ["0x1000", "missing", "0x2000"], topology_map
    )

    assert [(target.parent_rloc16, target.child_rloc16) for target in targets] == [
        ("0x1000", "0x1001"),
        ("0x1000", "0x1002"),
        ("0x2000", "0x2001"),
    ]
    assert targets[0].child_record["name"] == "first"
    targets[0].child_record["name"] = "changed"
    assert topology_map["0x1000"]["children"][0]["name"] == "first"


def test_fetch_child_with_retries_is_pure_and_obeys_terminal_states() -> None:
    fast, detail = topology.build_child_fetch_policies(True, True)
    calls: list[tuple[int, int]] = []
    delays: list[float] = []

    def fetch(target: topology.ChildFetchTarget, attempt: topology.ChildFetchAttempt):
        calls.append((attempt.index, attempt.detail_level))
        if attempt.index == 1:
            return {"rloc16": target.child_rloc16, "extaddr": "child-ext"}
        return None

    outcome = topology.fetch_child_with_retries(
        _target(), fast, {}, fetch, delays.append
    )
    assert calls == [(0, 1), (1, 1)]
    assert delays == [0.25]
    assert outcome.terminal_reason == "responded"
    assert outcome.observations[0]["last_attempt_responded"] == 1
    assert outcome.observations[0]["last_attempt_tlv_detail_level"] == 1

    calls.clear()
    skipped = topology.fetch_child_with_retries(
        _target(), detail, {"last_attempt_tlv_detail_level": 4}, fetch, delays.append
    )
    assert skipped.terminal_reason == "already-satisfied"
    assert calls == []

    retained = topology.fetch_child_with_retries(
        _target(), detail, {
            "last_attempt_responded": 0,
            "last_attempt_tlv_detail_level": 1,
        }, lambda _target, _attempt: None, delays.append
    )
    assert retained.terminal_reason == "retained-prior"
    assert len(retained.attempted) == 1

    responses = iter([
        {"rloc16": "0x1001", "extaddr": "child-ext"},
        None,
    ])
    retained_current = topology.fetch_child_with_retries(
        _target(), detail, {}, lambda _target, _attempt: next(responses), delays.append
    )
    assert retained_current.terminal_reason == "retained-prior"
    assert len(retained_current.observations) == 1
    assert len(retained_current.attempted) == 2

    detail_calls: list[int] = []
    complete = topology.fetch_child_with_retries(
        _target(),
        detail,
        {},
        lambda target, attempt: (
            detail_calls.append(attempt.detail_level)
            or {"rloc16": target.child_rloc16, "extaddr": "child-ext"}
        ),
        lambda seconds: pytest.fail(f"unexpected delay: {seconds}"),
    )
    assert detail_calls == [1, 2, 3, 3, 4]
    assert complete.terminal_reason == "responded"
    assert len(complete.observations) == 5

    failed_delays: list[float] = []
    exhausted = topology.fetch_child_with_retries(
        _target(), detail, {}, lambda _target, _attempt: None, failed_delays.append
    )
    assert [attempt.detail_level for attempt in exhausted.attempted] == [1, 2, 3]
    assert failed_delays == [0.25, 0.5]
    assert exhausted.terminal_reason == "exhausted"

    with pytest.raises(RuntimeError, match="transport"):
        topology.fetch_child_with_retries(
            _target(),
            fast,
            {},
            lambda _target, _attempt: (_ for _ in ()).throw(RuntimeError("transport")),
            delays.append,
        )


def test_child_expansion_reconciles_move_and_checkpoints_once(monkeypatch) -> None:
    network_topology_map = {
        "0x1000": {"rloc16": "0x1000", "children": [{"rloc16": "0x1001"}]},
        "0x0001": {"rloc16": "0x0001", "extaddr": "child-ext", "name": "prior"},
    }
    extaddr_to_rloc = {"child-ext": "0x0001"}
    fetch_calls: list[tuple[str, int]] = []
    checkpoints: list[dict] = []

    def fetch(rloc16, _prefix, _labels, _routers, _addresses, detail_level):
        fetch_calls.append((rloc16, detail_level))
        return {
            "rloc16": "0x1001",
            "extaddr": "child-ext",
            "device_label": "Child",
            "ipv6_addrs": [],
        }

    monkeypatch.setattr(topology, "fetch_network_diag_for_device", fetch)
    monkeypatch.setattr(topology.time, "sleep", lambda _seconds: pytest.fail("unexpected sleep"))
    monkeypatch.setattr(
        topology,
        "save_topology_to_json_file",
        lambda payload, _path: checkpoints.append(dict(payload)),
    )

    topology.fetch_network_diag_topology_expand_children(
        True,
        ["0x1000"],
        network_topology_map,
        {},
        {},
        {},
        None,
        None,
        extaddr_to_rloc,
        "checkpoint.json",
    )

    assert fetch_calls == [("0x1001", 1)]
    assert "0x0001" not in network_topology_map
    assert network_topology_map["0x1001"]["extaddr"] == "child-ext"
    assert extaddr_to_rloc["child-ext"] == "0x1001"
    assert len(checkpoints) == 1


def test_exhausted_child_inserts_one_fallback_but_retains_known_record(monkeypatch) -> None:
    monkeypatch.setattr(topology, "fetch_network_diag_for_device", lambda *_args: None)
    monkeypatch.setattr(topology.time, "sleep", lambda _seconds: None)
    checkpoints: list[dict] = []
    monkeypatch.setattr(
        topology,
        "save_topology_to_json_file",
        lambda payload, _path: checkpoints.append(dict(payload)),
    )
    topology_map = {
        "0x1000": {"children": [{"rloc16": "0x1001"}, {"rloc16": "0x1002"}]},
        "0x1002": {"rloc16": "0x1002", "extaddr": "known"},
    }

    topology.fetch_network_diag_topology_expand_children(
        True, ["0x1000"], topology_map, {}, {}, {}, None, None, {}, "checkpoint.json"
    )

    assert topology_map["0x1001"]["extaddr"] == "found-0x1001"
    assert topology_map["0x1001"]["network_diagnostic_status"] == "no-response"
    assert topology_map["0x1001"]["reachability"] == "unknown"
    assert topology_map["0x1001"]["ping"] == {"status": "not-attempted"}
    assert topology_map["0x1002"]["extaddr"] == "known"
    assert len(checkpoints) == 2


def test_reconciliation_reports_unchanged_and_replaces_found_placeholder() -> None:
    target = _target()
    unchanged = topology.ChildFetchOutcome(target, "detail", (), (), "already-satisfied")
    topology_map = {"0x1001": {"rloc16": "0x1001", "extaddr": "known"}}
    mutation = topology.reconcile_child_fetch_outcome(
        unchanged, topology_map, {"known": "0x1001"}, {}, None, None
    )
    assert mutation == topology.ChildMutation(False, "unchanged", "0x1001")

    exhausted = topology.ChildFetchOutcome(target, "fast", (), (), "exhausted")
    found_map = {
        "0x1001": {"rloc16": "0x1001", "extaddr": "found-0x1001"}
    }
    mutation = topology.reconcile_child_fetch_outcome(
        exhausted, found_map, {}, {}, None, None
    )
    assert mutation.kind == "fallback"
    assert found_map["0x1001"]["extaddr"] == "found-0x1001"
    assert found_map["0x1001"]["role"] == "child"

    responded = topology.ChildFetchOutcome(
        target,
        "fast",
        ({
            "rloc16": "0x1001",
            "extaddr": "0011223344556677",
            "device_label": "Kitchen Sensor",
        },),
        (),
        "responded",
    )
    mutation = topology.reconcile_child_fetch_outcome(
        responded, found_map, {}, {}, None, None
    )
    assert mutation.kind == "updated"
    assert found_map["0x1001"]["extaddr"] == "0011223344556677"
    assert found_map["0x1001"]["device_label"] == "Kitchen Sensor"


def test_child_ping_runs_once_after_all_diagnostic_policies_exhaust(monkeypatch) -> None:
    fetch_calls: list[int] = []
    ping_requests: list[topology.otbr_cli_device.PingRequest] = []
    topology_map = {
        "0x4c00": {
            "rloc16": "0x4c00",
            "ipv6_addrs": ["fd3b:a255:4aa6:5483:0:ff:fe00:4c00"],
            "children": [{"rloc16": "0x4c92"}],
        }
    }

    monkeypatch.setattr(
        topology,
        "fetch_network_diag_for_device",
        lambda *_args: fetch_calls.append(_args[-1]) or None,
    )
    monkeypatch.setattr(topology.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        topology.otbr_cli_device,
        "ping_device",
        lambda request: (
            ping_requests.append(request)
            or topology.otbr_cli_device.PingResult(
                target=request.target,
                source=None,
                container="otbr",
                sent=1,
                received=1,
                loss=0.0,
                round_trip_samples_ms=(12.0,),
                round_trip_summary_ms={"min": 12.0, "average": 12.0, "max": 12.0},
                timeout_seconds=3,
                observed_at="2026-09-07T00:00:00+00:00",
                error_category="none",
                output="",
            )
        ),
    )

    topology.fetch_network_diag_topology_expand_children(
        True,
        ["0x4c00"],
        topology_map,
        {},
        {},
        {},
        None,
        None,
        {},
        None,
        True,
        True,
        True,
    )

    assert fetch_calls == [1, 1, 1, 2, 3]
    assert [request.target for request in ping_requests] == [
        "fd3b:a255:4aa6:5483:0:ff:fe00:4c92"
    ]
    child = topology_map["0x4c92"]
    assert child["network_diagnostic_status"] == "no-response"
    assert child["reachability"] == "reachable"
    assert child["ping"]["status"] == "reply"
    assert child["ping"]["received"] == 1


def test_child_ping_unavailable_keeps_reachability_unknown(monkeypatch) -> None:
    monkeypatch.setattr(topology, "fetch_network_diag_for_device", lambda *_args: None)
    monkeypatch.setattr(topology.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        topology.otbr_cli_device,
        "ping_device",
        lambda _request: pytest.fail("ping should not run without a derived target"),
    )
    topology_map = {
        "0x1000": {"rloc16": "0x1000", "ipv6_addrs": [], "children": [{"rloc16": "0x1001"}]}
    }

    topology.fetch_network_diag_topology_expand_children(
        True, ["0x1000"], topology_map, {}, {}, {}, None, None, {}, None,
        children_ping_fallback=True,
    )

    assert topology_map["0x1001"]["reachability"] == "unknown"
    assert topology_map["0x1001"]["ping"] == {
        "status": "unavailable",
        "error_category": "target-unavailable",
    }


def test_checkpoint_notifier_serializes_full_partial_topology(tmp_path) -> None:
    checkpoint = tmp_path / "topology.partial.json"
    topology_map = {
        "0x1000": {
            "rloc16": "0x1000",
            "extaddr": "router-ext",
            "device_label": "Router",
            "children": [{"rloc16": "0x1001"}],
        },
        "0x1001": {
            "rloc16": "0x1001",
            "extaddr": "child-ext",
            "device_label": "Child",
            "type": "child",
        },
    }
    topology.notify_child_checkpoint(
        topology.ChildMutation(True, "added", "0x1001"),
        topology_map,
        str(checkpoint),
    )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert [record["rloc16"] for record in payload] == ["0x1000", "0x1001"]
    assert payload[0]["children"] == [{"rloc16": "0x1001"}]


def test_checkpoint_serializes_child_liveness_evidence(tmp_path) -> None:
    checkpoint = tmp_path / "topology.partial.json"
    topology.save_topology_to_json_file({
        "0x1001": {
            "rloc16": "0x1001",
            "extaddr": "found-0x1001",
            "last_attempt_responded": -1,
            "last_attempt_tlv_detail_level": 1,
            "network_diagnostic_status": "no-response",
            "reachability": "unknown",
            "ping": {"status": "no-reply", "timeout_seconds": 3},
        }
    }, checkpoint)

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))[0]
    assert payload["lastAttemptResponded"] == -1
    assert payload["lastAttemptTlvDetailLevel"] == 1
    assert payload["networkDiagnosticStatus"] == "no-response"
    assert payload["reachability"] == "unknown"
    assert payload["ping"] == {"status": "no-reply", "timeoutSeconds": 3}