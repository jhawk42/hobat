from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

import util_network
import util_ot_ctl
from td_json_key_normalizer import canonical_camel_key, convert_keys_to_camel_case


def test_key_normalizer_applies_explicit_and_recursive_rules_without_mutation() -> None:
    payload = {
        "extaddr": "aa00112233445566",
        "leader_data": {
            "partition_id": 7,
            "route_data": [{"route_cost": 2}],
        },
        3: {"device_label": "Kitchen"},
    }

    assert convert_keys_to_camel_case(payload) == {
        "extAddress": "aa00112233445566",
        "leaderData": {
            "partitionId": 7,
            "routeData": [{"routeCost": 2}],
        },
        3: {"deviceLabel": "Kitchen"},
    }
    assert payload["leader_data"]["route_data"][0] == {"route_cost": 2}
    assert canonical_camel_key("alreadyCamel") == "alreadyCamel"


def test_network_helpers_cover_prefix_identity_and_address_selection(monkeypatch) -> None:
    monkeypatch.setattr(util_network.util_ot_ctl, "exec_ot_ctl", lambda command: "fd00:1234::/64 Done")

    assert util_network.fetch_meshlocal_prefix() == "fd00:1234::/64"
    assert util_network.build_rloc_ipv6_address_prefix("fd00:1234::/64") == "fd00:1234:0:ff:fe00:"
    assert util_network.build_omr_ipv6_address_prefix("fd00:abcd::/64") == "fd00:abcd"
    assert util_network.is_router("0x4C00") is True
    assert util_network.is_router("0x4a01") is False
    assert util_network.is_router("invalid") is False
    assert util_network.derive_parent_rloc16("0x4c92") == "0x4c00"
    assert util_network.derive_parent_rloc16("0x4c00") is None
    assert util_network.is_child_rloc16_of_parent("0x4c92", "0x4c00") is True
    assert util_network.is_child_rloc16_of_parent("0x5092", "0x4c00") is False
    assert util_network.is_child_rloc16_of_parent("0x4c92", "0x4c01") is False
    assert util_network.find_omr_address_in_list(
        ["fd00:1234::1", "fd00:abcd::2"],
        "fd00:abcd",
    ) == "fd00:abcd::2"
    assert util_network.find_omr_address_in_list([], "fd00:abcd") is None


@pytest.mark.parametrize(
    ("fetcher", "command", "output", "expected"),
    [
        (util_network.fetch_meshlocal_prefix, "prefix meshlocal", "fd00::/64 done", "fd00::/64"),
        (util_network.fetch_omr_prefix, "br omrprefix favored", "fd12:3456::/56", "fd12:3456::/56"),
    ],
)
def test_network_prefix_fetchers_accept_valid_ipv6_networks(
    monkeypatch, fetcher, command, output, expected
) -> None:
    monkeypatch.setattr(
        util_network.util_ot_ctl,
        "exec_ot_ctl",
        lambda actual_command: output if actual_command == command else None,
    )

    assert fetcher() == expected


@pytest.mark.parametrize(
    "output",
    ["Error: command timed out after 30s", "", "not-a-prefix", "fd00::/129"],
)
@pytest.mark.parametrize("fetcher", [util_network.fetch_meshlocal_prefix, util_network.fetch_omr_prefix])
def test_network_prefix_fetchers_reject_invalid_ot_ctl_output(monkeypatch, fetcher, output) -> None:
    monkeypatch.setattr(util_network.util_ot_ctl, "exec_ot_ctl", lambda command: output)

    with pytest.raises(util_network.PrefixFetchError):
        fetcher()


def test_network_helpers_extract_rloc16_from_thread_ipv6_addresses() -> None:
    assert util_network.extract_rloc16_from_ipv6_address(
        "fd3b:a255:4aa6:5483:0:ff:fe00:1c05"
    ) == "0x1c05"
    assert util_network.extract_rloc16_from_ipv6_address(
        "FD3B:A255:4AA6:5483:0000:00FF:FE00:4C00"
    ) == "0x4c00"
    assert util_network.find_rloc16_in_ipv6_addresses(
        ["fe80::1", "fd3b:a255:4aa6:5483:0:ff:fe00:1c05"]
    ) == "0x1c05"
    assert util_network.extract_rloc16_from_ipv6_address("fd3b:a255::1c05") is None
    assert util_network.find_rloc16_in_ipv6_addresses(None) is None


def test_network_helpers_derive_child_rloc_from_parent_address() -> None:
    assert util_network.derive_child_rloc_ipv6_address(
        [
            "fd00:abcd::1",
            "FD3B:A255:4AA6:5483:0000:00FF:FE00:4C00",
        ],
        "0x4c00",
        "0x4c92",
    ) == "fd3b:a255:4aa6:5483:0:ff:fe00:4c92"


def test_network_helpers_reject_invalid_or_ambiguous_child_rloc_derivation() -> None:
    parent = "fd3b:a255:4aa6:5483:0:ff:fe00:4c00"
    assert util_network.derive_child_rloc_ipv6_address([parent], "0x4c00", "0x5092") is None
    assert util_network.derive_child_rloc_ipv6_address(["fd3b:a255::4c00"], "0x4c00", "0x4c92") is None
    assert util_network.derive_child_rloc_ipv6_address(
        [parent, "fd4b:a255:4aa6:5483:0:ff:fe00:4c00"],
        "0x4c00",
        "0x4c92",
    ) is None
    assert util_network.derive_child_rloc_ipv6_address(None, "0x4c00", "0x4c92") is None


def test_ot_ctl_dispatch_selects_container_command_and_timeout(monkeypatch) -> None:
    completed = Mock(stdout=" response\n")
    run = Mock(return_value=completed)
    monkeypatch.setattr(util_ot_ctl.subprocess, "run", run)
    monkeypatch.setenv(util_ot_ctl.TD_OT_CTL_TIMEOUT_ENV, "9")

    assert util_ot_ctl.exec_ot_ctl_dispatch("state", "otbr-test") == "response"
    run.assert_called_once_with(
        ["docker", "exec", "-i", "otbr-test", "sh", "-c", "ot-ctl state"],
        capture_output=True,
        text=True,
        check=True,
        timeout=9,
    )


def test_ot_ctl_dispatch_reports_timeout_and_command_failure(monkeypatch) -> None:
    monkeypatch.setenv(util_ot_ctl.TD_OT_CTL_TIMEOUT_ENV, "3")
    monkeypatch.setattr(
        util_ot_ctl.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired(["ot-ctl"], 3)),
    )
    assert util_ot_ctl.exec_ot_ctl_dispatch("state", None) == "Error: command timed out after 3s"

    monkeypatch.setattr(
        util_ot_ctl.subprocess,
        "run",
        Mock(side_effect=subprocess.CalledProcessError(7, ["ot-ctl"], stderr="denied")),
    )
    assert util_ot_ctl.exec_ot_ctl_dispatch("state", None) == "Error: denied"