from __future__ import annotations

import asyncio
import copy
import json

from dataclasses import replace
from pathlib import Path

import pytest

from ha_matter_ws_contract import MatterWsContractError
from ha_matter_ws_native_topology import (
    MAX_SAFE_JSON_INTEGER,
    NativeTopologyValidationLimits,
    validate_native_topology,
)
from ha_matter_ws_snapshots import MatterSnapshotSecurityError, assert_snapshot_safe
from ha_matter_ws_thread import (
    THREAD_DIAGNOSTIC_TERMINAL_REASONS,
    THREAD_DIAGNOSTIC_TRANSIENT_REASONS,
    ThreadValidationLimits,
    collect_selected_thread_diagnostics,
    coalesce_thread_diagnostics_batches,
    normalize_extended_pan_id,
    validate_border_router_entries,
    validate_thread_diagnostics_batch,
    validate_thread_diagnostics_batches,
)


FIXTURE = Path(__file__).parent / "fixtures" / "ha_matter_ws_thread_network_schema13.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _minimal_batch() -> dict:
    return {
        "extPanIdHex": "1122334455667788",
        "networkName": "",
        "collectedAt": 0,
        "source": "none",
        "nodes": [],
    }


def _minimal_topology() -> dict:
    return {
        "collected_at": 0,
        "nodes": [
            {"id": "a", "kind": "matter", "network_type": "unknown"},
            {"id": "b", "kind": "thread_unknown", "network_type": "thread"},
        ],
        "connections": [
            {
                "source": "a",
                "target": "b",
                "network": "thread",
                "strength": "unknown",
            }
        ],
    }


def test_schema_12_fixture_validates_and_projects_native_thread_products() -> None:
    fixture = _fixture()

    routers = validate_border_router_entries(fixture["borderRouters"])
    batches = validate_thread_diagnostics_batches(fixture["batches"])

    assert routers[0]["addresses"] == ["192.0.2.10", "2001:db8::10"]
    assert routers[0]["extensions"] == {"futureScalar": "retained"}
    node = batches[0]["nodes"][0]
    assert node["networkData"] == "0A0B0C0D"
    assert node["mleCounters"]["disabledTime"] == "9007199254740992"
    assert node["extensions"] == {"futureNodeScalar": True}
    assert_snapshot_safe({"borderRouters": routers, "batches": batches})


def test_schema_13_fixture_preserves_native_topology_and_optional_fields() -> None:
    topology = validate_native_topology(_fixture()["topology"])

    assert topology["nodes"][0]["node_id"] == "18446744073709551615"
    assert topology["nodes"][1]["host_name"] == "Border Router"
    assert topology["nodes"][2]["ssid"] == "Test WiFi"
    assert topology["nodes"][2]["bssid"] == "11:22:33:44:55:66"
    assert topology["nodes"][2]["extensions"] == {"futureNodeScalar": 7}
    assert topology["connections"][0]["strength"] == "unknown"
    assert topology["connections"][0]["target_to_source"] == {
        "strength": "unknown"
    }
    assert_snapshot_safe(topology)


def test_optional_post_schema_13_topology_fields_may_be_absent() -> None:
    topology = validate_native_topology(_minimal_topology())

    assert "host_name" not in topology["nodes"][0]
    assert "ssid" not in topology["nodes"][0]
    assert "bssid" not in topology["nodes"][0]


def test_empty_native_collections_are_valid() -> None:
    assert validate_border_router_entries([]) == []
    assert validate_thread_diagnostics_batches([]) == []
    assert validate_thread_diagnostics_batch(_minimal_batch())["nodes"] == []
    assert validate_native_topology(
        {"collected_at": 0, "nodes": [], "connections": []}
    )["connections"] == []


def test_diagnostic_batch_coalescing_keeps_latest_and_first_equal_conflict() -> None:
    first = {**_minimal_batch(), "collectedAt": 10, "source": "meshcop"}
    stale = {**_minimal_batch(), "collectedAt": 9, "source": "otbr-rest"}
    latest = {**_minimal_batch(), "collectedAt": 11, "source": "meshcop"}
    duplicate = copy.deepcopy(latest)
    conflict = {**latest, "source": "otbr-rest"}

    result = coalesce_thread_diagnostics_batches(
        [first, stale, latest, duplicate, conflict]
    )

    assert result.batches == (latest,)
    assert result.stale_count == 2
    assert result.duplicate_count == 1
    assert result.conflict_count == 1
    assert len(result.warnings) == 1


class FakeProgressiveClient:
    def __init__(self, response, events=(), *, event_during_request=None, error=None):
        self.response = response
        self.pending_events = list(events)
        self.event_during_request = event_during_request
        self.error = error
        self.sequenced_events = []
        self.requests = []
        self.cursor_captured_before_request = False

    @property
    def event_cursor(self):
        self.cursor_captured_before_request = not self.requests
        return len(self.sequenced_events)

    async def request(self, command, **kwargs):
        self.requests.append((command, kwargs))
        if self.event_during_request is not None:
            self.sequenced_events.append(
                (len(self.sequenced_events) + 1, self.event_during_request)
            )
        return copy.deepcopy(self.response)

    async def next_event(self, *, after, predicate, timeout=None):
        while self.pending_events:
            self.sequenced_events.append(
                (len(self.sequenced_events) + 1, self.pending_events.pop(0))
            )
        for sequence, event in self.sequenced_events:
            if sequence > after and predicate(event):
                return sequence, copy.deepcopy(event)
        await asyncio.sleep(0)
        raise asyncio.TimeoutError

    def raise_if_reader_failed(self):
        if self.error is not None:
            raise self.error


def _diagnostic_event(batch):
    return {"event": "thread_diagnostics_updated", "data": batch}


def test_selected_diagnostics_consumes_complete_event_arriving_before_response() -> None:
    transient = {
        **_minimal_batch(),
        "collectedAt": 1,
        "partialReason": "in_progress",
    }
    complete = {**_minimal_batch(), "collectedAt": 2, "source": "meshcop"}
    client = FakeProgressiveClient(
        transient, event_during_request=_diagnostic_event(complete)
    )
    checkpoints = []

    result = asyncio.run(
        collect_selected_thread_diagnostics(
            client,
            "1122334455667788",
            force=True,
            timeout=1,
            checkpoint=checkpoints.append,
        )
    )

    assert result.status == "complete"
    assert result.batch == complete
    assert result.response_count == 1
    assert result.event_count == 1
    assert result.accepted_count == 2
    assert checkpoints == [transient]
    assert client.cursor_captured_before_request is True
    assert client.requests[0][0:1] == ("get_thread_diagnostics",)
    assert client.requests[0][1]["args"] == {
        "ext_pan_id": "1122334455667788",
        "force": True,
    }


def test_selected_diagnostics_coalesces_progressive_events_by_timestamp() -> None:
    transient = {
        **_minimal_batch(),
        "collectedAt": 2,
        "partialReason": "in_progress",
    }
    other = {**transient, "extPanIdHex": "AABBCCDDEEFF0011", "collectedAt": 9}
    stale = {**transient, "collectedAt": 1}
    duplicate = copy.deepcopy(transient)
    conflict = {**transient, "source": "meshcop"}
    complete = {**_minimal_batch(), "collectedAt": 3, "source": "meshcop"}
    client = FakeProgressiveClient(
        transient,
        events=[
            _diagnostic_event(other),
            _diagnostic_event(stale),
            _diagnostic_event(duplicate),
            _diagnostic_event(conflict),
            _diagnostic_event(complete),
        ],
    )

    result = asyncio.run(
        collect_selected_thread_diagnostics(
            client, "1122334455667788", force=False, timeout=1
        )
    )

    assert result.status == "complete"
    assert result.batch == complete
    assert result.event_count == 4
    assert result.stale_count == 1
    assert result.duplicate_count == 1
    assert result.conflict_count == 1
    assert len(result.warnings) == 1


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (None, "unavailable"),
        ({**_minimal_batch(), "partialReason": "no_source"}, "partial"),
        ({**_minimal_batch(), "partialReason": "in_progress"}, "partial"),
    ],
)
def test_selected_diagnostics_noncomplete_states(response, expected_status) -> None:
    client = FakeProgressiveClient(response)
    checkpoints = []

    result = asyncio.run(
        collect_selected_thread_diagnostics(
            client,
            "1122334455667788",
            force=False,
            timeout=0.01,
            checkpoint=checkpoints.append,
        )
    )

    assert result.status == expected_status
    assert bool(checkpoints) is (response is not None)
    assert len(checkpoints) <= 1


@pytest.mark.parametrize("reason", sorted(THREAD_DIAGNOSTIC_TERMINAL_REASONS))
def test_selected_diagnostics_accepts_every_terminal_reason(reason) -> None:
    response = {**_minimal_batch(), "partialReason": reason}

    result = asyncio.run(
        collect_selected_thread_diagnostics(
            FakeProgressiveClient(response),
            "1122334455667788",
            force=False,
            timeout=0.01,
        )
    )

    assert result.status == "partial"
    assert result.batch["partialReason"] == reason


@pytest.mark.parametrize("reason", sorted(THREAD_DIAGNOSTIC_TRANSIENT_REASONS))
def test_selected_diagnostics_accepts_every_transient_reason(reason) -> None:
    response = {**_minimal_batch(), "partialReason": reason}
    complete = {**_minimal_batch(), "collectedAt": 1, "source": "meshcop"}

    result = asyncio.run(
        collect_selected_thread_diagnostics(
            FakeProgressiveClient(response, [_diagnostic_event(complete)]),
            "1122334455667788",
            force=False,
            timeout=1,
        )
    )

    assert result.status == "complete"


def test_selected_diagnostics_surfaces_reader_failure() -> None:
    response = {**_minimal_batch(), "partialReason": "in_progress"}
    client = FakeProgressiveClient(
        response, error=MatterWsContractError("reader failed")
    )

    with pytest.raises(MatterWsContractError, match="reader failed"):
        asyncio.run(
            collect_selected_thread_diagnostics(
                client,
                "1122334455667788",
                force=False,
                timeout=0.01,
            )
        )


def test_selected_diagnostics_propagates_cancellation() -> None:
    response = {**_minimal_batch(), "partialReason": "in_progress"}
    client = FakeProgressiveClient(response)

    async def cancel(**kwargs):
        raise asyncio.CancelledError

    client.next_event = cancel
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            collect_selected_thread_diagnostics(
                client,
                "1122334455667788",
                force=False,
                timeout=1,
            )
        )


def test_selected_diagnostics_normalizes_and_rejects_extended_pan_id() -> None:
    assert normalize_extended_pan_id("AABBCCDDEEFF0011") == "aabbccddeeff0011"
    with pytest.raises(MatterWsContractError, match="exactly 16"):
        normalize_extended_pan_id("AABB")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("extAddressHex", "ABC", "exactly 16"),
        ("addresses", ["not-an-address"], "IPv4 or IPv6"),
        ("sources", [], "must not be empty"),
        ("sources", ["dns"], "must be one of"),
        ("meshcopPort", 0, "1 through 65535"),
        ("stateBitmapHex", "00", "exactly 8"),
        ("lastSeen", -1, "0 through"),
    ],
)
def test_border_router_rejects_malformed_fields(field, value, message) -> None:
    router = copy.deepcopy(_fixture()["borderRouters"][0])
    router[field] = value

    with pytest.raises(MatterWsContractError, match=message):
        validate_border_router_entries([router])


def test_border_router_limits_accept_boundary_and_reject_one_over() -> None:
    router = {
        "extAddressHex": "AABBCCDDEEFF0011",
        "addresses": ["192.0.2.1"],
        "sources": ["meshcop"],
    }
    limits = ThreadValidationLimits(max_border_routers=1, max_addresses_per_router=1)

    assert validate_border_router_entries([router], limits=limits) == [router]
    with pytest.raises(MatterWsContractError, match="limit of 1"):
        validate_border_router_entries([router, router], limits=limits)
    router["addresses"].append("192.0.2.2")
    with pytest.raises(MatterWsContractError, match="limit of 1"):
        validate_border_router_entries([router], limits=limits)


def test_diagnostic_collection_limits_accept_boundaries_and_reject_one_over() -> None:
    batch = _minimal_batch()
    node = {
        "ipv6Addresses": ["FD000000000000000000000000000001"],
        "route64": {"idSequence": 0, "entries": []},
        "childTable": [],
        "unknown": [{"type": 1, "value": "AA"}],
    }
    batch["nodes"] = [node]
    limits = ThreadValidationLimits(
        max_networks=1,
        max_nodes_per_network=1,
        max_ipv6_addresses_per_node=1,
        max_route64_entries_per_node=1,
        max_child_table_entries_per_node=1,
        max_unknown_tlvs_per_node=1,
        max_unknown_tlv_hex_bytes=1,
    )

    assert len(validate_thread_diagnostics_batches([batch], limits=limits)) == 1
    with pytest.raises(MatterWsContractError, match="limit of 1"):
        validate_thread_diagnostics_batches([batch, batch], limits=limits)
    batch["nodes"].append({})
    with pytest.raises(MatterWsContractError, match="limit of 1"):
        validate_thread_diagnostics_batches([batch], limits=limits)


@pytest.mark.parametrize(
    ("field", "boundary_value", "one_over_value"),
    [
        (
            "ipv6Addresses",
            ["FD000000000000000000000000000001"],
            [
                "FD000000000000000000000000000001",
                "FD000000000000000000000000000002",
            ],
        ),
        (
            "route64",
            {
                "idSequence": 0,
                "entries": [
                    {
                        "routerId": 1,
                        "linkQualityIn": 1,
                        "linkQualityOut": 1,
                        "routeCost": 1,
                    }
                ],
            },
            {
                "idSequence": 0,
                "entries": [
                    {
                        "routerId": 1,
                        "linkQualityIn": 1,
                        "linkQualityOut": 1,
                        "routeCost": 1,
                    },
                    {
                        "routerId": 2,
                        "linkQualityIn": 1,
                        "linkQualityOut": 1,
                        "routeCost": 1,
                    },
                ],
            },
        ),
        (
            "childTable",
            [
                {
                    "timeoutExponent": 1,
                    "timeoutSeconds": 2,
                    "incomingLinkQuality": 1,
                    "childId": 1,
                    "mode": {
                        "rxOnWhenIdle": False,
                        "ftd": False,
                        "fullNetworkData": False,
                    },
                }
            ],
            [
                {
                    "timeoutExponent": 1,
                    "timeoutSeconds": 2,
                    "incomingLinkQuality": 1,
                    "childId": 1,
                    "mode": {
                        "rxOnWhenIdle": False,
                        "ftd": False,
                        "fullNetworkData": False,
                    },
                },
                {
                    "timeoutExponent": 1,
                    "timeoutSeconds": 2,
                    "incomingLinkQuality": 1,
                    "childId": 2,
                    "mode": {
                        "rxOnWhenIdle": False,
                        "ftd": False,
                        "fullNetworkData": False,
                    },
                },
            ],
        ),
        (
            "unknown",
            [{"type": 1, "value": "AA"}],
            [{"type": 1, "value": "AA"}, {"type": 2, "value": "BB"}],
        ),
    ],
)
def test_diagnostic_nested_collection_limits_accept_boundary_and_reject_one_over(
    field, boundary_value, one_over_value
) -> None:
    limits = ThreadValidationLimits(
        max_ipv6_addresses_per_node=1,
        max_route64_entries_per_node=1,
        max_child_table_entries_per_node=1,
        max_unknown_tlvs_per_node=1,
    )
    batch = _minimal_batch()
    batch["nodes"] = [{field: boundary_value}]
    assert validate_thread_diagnostics_batch(batch, limits=limits)["nodes"]

    batch["nodes"] = [{field: one_over_value}]
    with pytest.raises(MatterWsContractError, match="limit of 1"):
        validate_thread_diagnostics_batch(batch, limits=limits)


def test_generic_text_limit_counts_utf8_bytes_at_boundary() -> None:
    batch = _minimal_batch()
    limits = ThreadValidationLimits(max_text_bytes=4)
    batch["networkName"] = "éé"
    assert validate_thread_diagnostics_batch(batch, limits=limits)["networkName"] == "éé"

    batch["networkName"] = "ééé"
    with pytest.raises(MatterWsContractError, match="4 UTF-8 bytes"):
        validate_thread_diagnostics_batch(batch, limits=limits)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda node: node.update(extMacAddress="bad"), "exactly 16"),
        (lambda node: node.update(mode={"rxOnWhenIdle": 1, "ftd": True, "fullNetworkData": True}), "must be boolean"),
        (lambda node: node.update(networkData="ABC"), "even number"),
        (lambda node: node.update(ipv6Addresses=["00"]), "exactly 32"),
        (lambda node: node.update(mleCounters={**node["mleCounters"], "trackedTime": MAX_SAFE_JSON_INTEGER + 1}), "safe JSON integer"),
        (lambda node: node.update(mleCounters={**node["mleCounters"], "trackedTime": "18446744073709551616"}), "uint64 decimal string"),
        (lambda node: node.update(unknown=[{"type": 1, "value": "GG"}]), "hexadecimal"),
        (lambda node: node.update(futureObject={"nested": True}), "bounded JSON scalar"),
    ],
)
def test_diagnostic_node_rejects_malformed_nested_values(mutator, message) -> None:
    batch = copy.deepcopy(_fixture()["batches"][0])
    mutator(batch["nodes"][0])

    with pytest.raises(MatterWsContractError, match=message):
        validate_thread_diagnostics_batch(batch)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "unknown-source"),
        ("partialReason", "future-reason"),
        ("collectedAt", -1),
    ],
)
def test_diagnostic_batch_rejects_invalid_enums_and_timestamp(field, value) -> None:
    batch = _minimal_batch()
    batch[field] = value

    with pytest.raises(MatterWsContractError):
        validate_thread_diagnostics_batch(batch)


def test_unknown_tlv_decoded_size_limit_is_enforced() -> None:
    batch = _minimal_batch()
    batch["nodes"] = [{"unknown": [{"type": 1, "value": "AABB"}]}]
    limits = ThreadValidationLimits(max_unknown_tlv_hex_bytes=1)

    with pytest.raises(MatterWsContractError, match="decoded hex limit"):
        validate_thread_diagnostics_batch(batch, limits=limits)


def test_extension_mapping_is_bounded_and_rejects_structural_values() -> None:
    batch = _minimal_batch()
    batch["extensions"] = {"one": 1, "two": "two"}
    limits = ThreadValidationLimits(max_extension_fields=2)

    assert validate_thread_diagnostics_batch(batch, limits=limits)["extensions"] == {
        "one": 1,
        "two": "two",
    }
    batch["extensions"]["three"] = 3
    with pytest.raises(MatterWsContractError, match="limit of 2"):
        validate_thread_diagnostics_batch(batch, limits=limits)
    batch["extensions"] = {"nested": []}
    with pytest.raises(MatterWsContractError, match="bounded JSON scalar"):
        validate_thread_diagnostics_batch(batch, limits=limits)


def test_snapshot_safety_allows_network_data_but_rejects_credentials() -> None:
    assert_snapshot_safe({"networkData": "0A0B"})
    for key in ("operationalCredentials", "networkKey", "pskc", "activeDataset", "acl"):
        with pytest.raises(MatterSnapshotSecurityError):
            assert_snapshot_safe({key: "forbidden"})


def test_native_validators_reject_credential_shaped_extensions() -> None:
    batch = _minimal_batch()
    batch["pskc"] = "forbidden"
    with pytest.raises(MatterSnapshotSecurityError):
        validate_thread_diagnostics_batch(batch)

    topology = _minimal_topology()
    topology["networkKey"] = "forbidden"
    with pytest.raises(MatterSnapshotSecurityError):
        validate_native_topology(topology)


def test_topology_limits_accept_boundaries_and_reject_one_over() -> None:
    topology = _minimal_topology()
    limits = NativeTopologyValidationLimits(max_nodes=2, max_connections=1)

    assert len(validate_native_topology(topology, limits=limits)["nodes"]) == 2
    topology["nodes"].append(
        {"id": "c", "kind": "wifi_ap", "network_type": "wifi"}
    )
    with pytest.raises(MatterWsContractError, match="limit of 2"):
        validate_native_topology(topology, limits=limits)
    topology = _minimal_topology()
    topology["connections"].append(copy.deepcopy(topology["connections"][0]))
    with pytest.raises(MatterWsContractError, match="limit of 1"):
        validate_native_topology(topology, limits=limits)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda topology: topology["nodes"].append(copy.deepcopy(topology["nodes"][0])), "must be unique"),
        (lambda topology: topology["connections"][0].update(target="missing"), "existing node id"),
        (lambda topology: topology["nodes"][0].update(kind="future_kind"), "must be one of"),
        (lambda topology: topology["nodes"][0].update(role="root"), "must be one of"),
        (lambda topology: topology["nodes"][0].update(node_id=MAX_SAFE_JSON_INTEGER + 1), "safe JSON integer"),
        (lambda topology: topology["connections"][0].update(strength="excellent"), "must be one of"),
        (lambda topology: topology["connections"][0].update(source_to_target={"strength": "strong", "lqi": 4}), "0 through 3"),
        (lambda topology: topology["nodes"][0].update(future={"nested": True}), "bounded JSON scalar"),
    ],
)
def test_topology_rejects_invalid_structure(mutation, message) -> None:
    topology = _minimal_topology()
    mutation(topology)

    with pytest.raises(MatterWsContractError, match=message):
        validate_native_topology(topology)


def test_topology_rejects_malformed_present_bssid() -> None:
    topology = _minimal_topology()
    topology["nodes"][0]["bssid"] = "112233445566"

    with pytest.raises(MatterWsContractError, match="BSSID"):
        validate_native_topology(topology)
