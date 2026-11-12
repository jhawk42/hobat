from __future__ import annotations

import subprocess
import logging
from unittest.mock import Mock

import pytest

import util_network
import util_ot_ctl
from td_json_key_normalizer import canonical_camel_key, convert_keys_to_camel_case


def test_key_normalizer_applies_explicit_and_recursive_rules_without_mutation() -> None:
    payload = {
        "extaddr": "aa00112233445566",
        "is_primary_bbr": True,
        "leader_data": {
            "partition_id": 7,
            "route_data": [{"route_cost": 2}],
        },
        3: {"device_label": "Kitchen"},
    }

    assert convert_keys_to_camel_case(payload) == {
        "extAddress": "aa00112233445566",
        "isPrimaryBBR": True,
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
    rloc_prefix = util_network.build_rloc_ipv6_address_prefix("fd00:1234::/64")
    assert util_network.build_rloc16_ipv6_address(rloc_prefix, "0400") == "fd00:1234:0:0:0:ff:fe00:0400"
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
        "fd00:abcd::/64",
    ) == "fd00:abcd::2"
    assert util_network.find_omr_address_in_list([], "fd00:abcd::/64") is None


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


@pytest.mark.parametrize(
    ("output", "output_state"),
    [
        ("Done\n", "completion_only"),
        ("", "empty"),
        ("Error: command timed out after 30s", "invalid_prefix"),
        ("network_key=not-for-events", "invalid_prefix"),
    ],
)
def test_prefix_failure_events_explain_output_without_exposing_it(
    monkeypatch, caplog, output, output_state
) -> None:
    calls = []
    monkeypatch.setattr(
        util_network.util_ot_ctl, "exec_ot_ctl",
        lambda command: calls.append(command) or output,
    )
    caplog.set_level("INFO")

    with pytest.raises(util_network.PrefixFetchError):
        util_network.fetch_meshlocal_prefix()

    assert calls == ["prefix meshlocal"]
    assert 'event="operation_end"' in caplog.text
    assert 'command="prefix meshlocal"' in caplog.text
    assert 'state="raised"' in caplog.text
    assert f'output_state="{output_state}"' in caplog.text
    assert 'error_type="PrefixFetchError"' in caplog.text
    assert "not-for-events" not in caplog.text


def test_prefix_success_inside_handled_exception_reports_returned(monkeypatch, caplog):
    monkeypatch.setattr(
        util_network.util_ot_ctl, "exec_ot_ctl",
        lambda _command: "fd00::/64\nDone",
    )
    caplog.set_level("INFO")
    try:
        raise RuntimeError("caller failure")
    except RuntimeError:
        assert util_network.fetch_meshlocal_prefix() == "fd00::/64"

    assert 'state="returned"' in caplog.text
    assert 'output_state="valid_prefix"' in caplog.text
    assert 'error_type="RuntimeError"' not in caplog.text


def test_prefix_transport_failure_propagates_with_correlated_event(monkeypatch, caplog):
    failure = OSError("private transport detail")
    calls = []

    def execute(command):
        calls.append(command)
        raise failure

    monkeypatch.setattr(util_network.util_ot_ctl, "exec_ot_ctl", execute)
    monkeypatch.setenv("TD_RUN_CMD", "prefix-check")
    caplog.set_level("INFO")

    with pytest.raises(OSError) as caught:
        util_network.fetch_meshlocal_prefix()

    assert caught.value is failure
    assert calls == ["prefix meshlocal"]
    assert 'run_cmd="prefix-check"' in caplog.text
    assert 'output_state="unavailable"' in caplog.text
    assert 'state="raised"' in caplog.text
    assert 'error_type="OSError"' in caplog.text
    assert "private transport detail" not in caplog.text


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


@pytest.mark.parametrize(("prefix", "inside", "outside"), [
    ("fda5:494c:9a12:0::/64", "fda5:494c:9a12::1234", "fda5:494c:9a12:01::1234"),
    ("fd00:abcd:1234:5600::/56", "fd00:abcd:1234:56ff:ffff:ffff:ffff:ffff", "fd00:abcd:1234:5700::"),
])
def test_omr_membership_respects_cidr_boundaries(prefix, inside, outside):
    assert util_network.is_ipv6_address_in_omr_prefix(inside, prefix)
    assert not util_network.is_ipv6_address_in_omr_prefix(outside, prefix)
    assert util_network.find_omr_address_in_list([outside, inside], prefix) == inside


def test_omr_selection_skips_bad_entries_and_preserves_original_spelling(caplog):
    address = "FD00:ABCD:0000:0000:0000:0000:0000:0002"
    assert util_network.find_omr_address_in_list(
        [None, "not-an-address", "192.0.2.1", address], "fd00:abcd::/64"
    ) == address
    assert len(caplog.records) == 1
    with pytest.raises(ValueError, match="explicit"):
        util_network.find_omr_address_in_list([], "fd00:abcd")


@pytest.mark.parametrize("info", [
    {"prefix_omr_ipv6addr_prefix": "fd00:abcd"},
    {"prefix_omr": "fd00:abcd"},
    {"prefix_omr": None},
    {"prefix_omr": "fd00:abcd::/64", "prefixOmr": "fd00:abcd:1::/64"},
])
def test_omr_resolution_never_guesses_or_ignores_conflicts(info, caplog):
    assert util_network.resolve_omr_network(info) is None
    assert caplog.records


def test_omr_resolution_accepts_equivalent_aliases_without_mutation():
    info = {"prefix_omr": "FD00:ABCD:0000:0000::/56", "prefixOmr": "fd00:abcd::/56",
            "prefix_omr_ipv6addr_prefix": "fd00:abcd"}
    before = dict(info)
    assert util_network.resolve_omr_network(info) == "fd00:abcd::/56"
    assert util_network.resolve_omr_network(None) is None
    assert util_network.resolve_omr_network({}) is None
    assert info == before


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("192.168.4.212", (True, "ipv4-infrastructure")),
        ("fd6b:32e0:d18::fa05:e6f5:15e3:d06f", (True, "off-mesh-candidate")),
        ("fe80::4871:9152:4c53:68d3", (False, "ipv6-link-local")),
        ("fd3b:a255:4aa6:5483:0:ff:fe00:4ce9", (False, "thread-rloc")),
        ("fd78:b977:5b00:1cbe:2:fdc2:e3c2:7ad7", (False, "thread-interface-signature")),
        ("not-an-address", (False, "invalid-address")),
        (None, (False, "invalid-address")),
        ("ff03::1", (False, "ipv6-multicast")),
        ("::1", (False, "ipv6-loopback")),
        ("::", (False, "ipv6-unspecified")),
    ],
)
def test_network_helpers_classify_off_mesh_address_candidates(address, expected) -> None:
    assert util_network.is_off_mesh_address(address) == expected


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
    completed = subprocess.CompletedProcess([], 0, stdout=" response\n", stderr="")
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


@pytest.mark.parametrize("stdout", ["", " \n", "\u00e9\n", "PRIVATE_STDOUT\n"])
def test_ot_ctl_dispatch_reports_zero_exit_stderr_without_changing_stdout(
    monkeypatch, caplog, capsys, stdout
):
    stderr = 'warning: network_key=PRIVATE_KEY\nPSKc: PRIVATE_PSKC\n'
    completed = subprocess.CompletedProcess([], 0, stdout=stdout, stderr=stderr)
    run = Mock(return_value=completed)
    monkeypatch.setattr(util_ot_ctl.subprocess, "run", run)
    monkeypatch.setenv("TD_RUN_CMD", "transport-check")
    monkeypatch.setenv("TD_LOG_THREAD_SECRETS", "1")
    caplog.set_level(logging.INFO)

    assert util_ot_ctl.exec_ot_ctl_dispatch("state", None) == stdout.strip()

    record, = [
        record for record in caplog.records
        if 'event="transport_end"' in record.getMessage()
    ]
    message = record.getMessage()
    assert record.levelno == logging.WARNING
    assert 'run_cmd="transport-check"' in message
    assert 'mode="local"' in message
    assert 'state="returned"' in message
    assert 'exit=0' in message
    assert f"stdout_bytes={len(stdout.encode('utf-8'))}" in message
    assert f"stderr_bytes={len(stderr.encode('utf-8'))}" in message
    assert f'stdout_empty={str(not stdout.strip()).lower()}' in message
    assert 'stderr_present=true' in message
    assert "warning:" in message
    assert "\n" not in message
    assert "PRIVATE_KEY" not in caplog.text
    assert "PRIVATE_PSKC" not in caplog.text
    assert "PRIVATE_STDOUT" not in caplog.text
    assert capsys.readouterr().out == ""
    run.assert_called_once()


@pytest.mark.parametrize("stdout", ["router\nDone\n", ""])
def test_ot_ctl_dispatch_reports_empty_stdout_and_elapsed_without_stderr(
    monkeypatch, caplog, stdout
):
    monkeypatch.setattr(
        util_ot_ctl.subprocess, "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")),
    )
    ticks = iter([10.0, 10.25])
    monkeypatch.setattr(util_ot_ctl.time, "monotonic", lambda: next(ticks))
    caplog.set_level(logging.INFO)

    assert util_ot_ctl.exec_ot_ctl_dispatch("state", "otbr-test") == stdout.strip()

    record, = [r for r in caplog.records if 'event="transport_end"' in r.getMessage()]
    assert record.levelno == (logging.INFO if stdout else logging.WARNING)
    assert 'mode="docker"' in record.getMessage()
    assert 'elapsed_s=0.25' in record.getMessage()
    assert 'stderr_bytes=0' in record.getMessage()
    assert 'stderr_present=false' in record.getMessage()


@pytest.mark.parametrize(
    ("failure", "state", "exit_code", "expected"),
    [
        (subprocess.CalledProcessError(
            7, ["ot-ctl"], output="partial", stderr="token=PRIVATE_TOKEN"
        ), "failed", "7", "Error: token=[Redacted]"),
        (subprocess.TimeoutExpired(
            ["ot-ctl"], 3, output=b"partial", stderr=b"token=PRIVATE_TOKEN"
        ), "timeout", "null", "Error: command timed out after 3s"),
    ],
)
def test_ot_ctl_dispatch_failure_metadata_preserves_existing_returns(
    monkeypatch, caplog, failure, state, exit_code, expected
):
    monkeypatch.setenv(util_ot_ctl.TD_OT_CTL_TIMEOUT_ENV, "3")
    monkeypatch.setattr(util_ot_ctl.subprocess, "run", Mock(side_effect=failure))
    caplog.set_level(logging.INFO)

    assert util_ot_ctl.exec_ot_ctl_dispatch("state", None) == expected

    record, = [r for r in caplog.records if 'event="transport_end"' in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert f'state="{state}"' in record.getMessage()
    assert f'exit={exit_code}' in record.getMessage()
    assert 'stdout_bytes=7' in record.getMessage()
    assert 'stderr_present=true' in record.getMessage()
    assert "PRIVATE_TOKEN" not in caplog.text


def test_ot_ctl_dispatch_unavailable_capture_is_not_reported_as_empty(
    monkeypatch, caplog
):
    failure = OSError("transport unavailable")
    monkeypatch.setattr(util_ot_ctl.subprocess, "run", Mock(side_effect=failure))
    caplog.set_level(logging.INFO)

    with pytest.raises(OSError) as caught:
        util_ot_ctl.exec_ot_ctl_dispatch("state")

    assert caught.value is failure
    record, = [r for r in caplog.records if 'event="transport_end"' in r.getMessage()]
    assert 'state="raised"' in record.getMessage()
    assert 'exit=null' in record.getMessage()
    assert 'stdout_bytes=null' in record.getMessage()
    assert 'stderr_bytes=null' in record.getMessage()
    assert 'stdout_empty=null' in record.getMessage()
    assert 'stderr_present=null' in record.getMessage()