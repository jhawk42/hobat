from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import otbr_cli_device
import td_cli


def test_ping_materializes_positional_defaults_and_reports_json(capsys) -> None:
    with patch.object(
        otbr_cli_device.util_ot_ctl,
        "exec_ot_ctl",
        return_value=(
            "16 bytes from 2001:db8::1: icmp_seq=1 hlim=64 time=4ms\n"
            "1 packets transmitted, 1 packets received. "
            "Packet loss = 0.0%. Round-trip min/avg/max = 4/4.000/4 ms.\nDone"
        ),
    ) as exec_ot_ctl:
        assert otbr_cli_device.main(["ping", "2001:db8::1", "--json"]) == 0

    exec_ot_ctl.assert_called_once_with("ping 2001:db8::1 56 1 1 64 3")
    result = json.loads(capsys.readouterr().out)
    assert result["sent"] == 1
    assert result["received"] == 1
    assert result["roundTripSamplesMs"] == [4.0]
    assert result["errorCategory"] == "none"


def test_ping_source_and_later_options_preserve_open_thread_positions() -> None:
    with patch.object(
        otbr_cli_device.util_ot_ctl,
        "exec_ot_ctl",
        return_value="1 packets transmitted, 0 packets received. Packet loss = 100.0%.\nDone",
    ) as exec_ot_ctl:
        assert otbr_cli_device.main(
            ["ping", "2001:db8::1", "--source", "2001:db8::2", "--timeout", "7"]
        ) == 0

    exec_ot_ctl.assert_called_once_with("ping -I 2001:db8::2 2001:db8::1 56 1 1 64 7")


def test_ping_device_uses_summary_counts_and_classifies_incomplete_output() -> None:
    request = otbr_cli_device.PingRequest(target="2001:db8::1")

    with patch.object(
        otbr_cli_device.util_ot_ctl,
        "exec_ot_ctl",
        return_value="1 packets transmitted, 0 packets received. Packet loss = 100.0%.\nDone",
    ):
        no_reply = otbr_cli_device.ping_device(request)
    assert no_reply.sent == 1
    assert no_reply.received == 0
    assert no_reply.error_category == "timeout"

    with patch.object(otbr_cli_device.util_ot_ctl, "exec_ot_ctl", return_value="Done"):
        incomplete = otbr_cli_device.ping_device(request)
    assert incomplete.error_category == "incomplete-output"


@pytest.mark.parametrize("target", ["ff03::1", "::", "::1", "fe80::1", "::ffff:192.0.2.1", "2001:db8::1%eth0", "2001:db8::1;state"])
def test_ping_rejects_special_or_injection_shaped_targets(target: str) -> None:
    with pytest.raises(SystemExit), patch.object(otbr_cli_device.util_ot_ctl, "exec_ot_ctl") as exec_ot_ctl:
        otbr_cli_device.main(["ping", target])
    exec_ot_ctl.assert_not_called()


def test_ping_rejects_duration_above_otbr_timeout() -> None:
    with pytest.raises(ValueError, match="30-second"):
        otbr_cli_device.main(["ping", "2001:db8::1", "--count", "10", "--interval", "5"])


@pytest.mark.parametrize(
    ("counters", "expected"),
    [("mac", "9"), ("mle", "34"), ("both", "9 34")],
)
def test_reset_constructs_only_fixed_counter_tlvs(counters: str, expected: str) -> None:
    with patch.object(otbr_cli_device.util_ot_ctl, "exec_ot_ctl", return_value="Done") as exec_ot_ctl:
        assert otbr_cli_device.main(
            ["reset-counters", "2001:db8::1", "--counters", counters, "--confirm"]
        ) == 0
    exec_ot_ctl.assert_called_once_with(f"networkdiagnostic reset 2001:db8::1 {expected}")


def test_reset_requires_explicit_confirmation() -> None:
    with pytest.raises(ValueError, match="requires --confirm"), patch.object(
        otbr_cli_device.util_ot_ctl, "exec_ot_ctl"
    ) as exec_ot_ctl:
        otbr_cli_device.main(["reset-counters", "2001:db8::1", "--counters", "mac"])
    exec_ot_ctl.assert_not_called()


def test_reset_reports_local_dispatch_failure_as_nonzero(capsys) -> None:
    with patch.object(otbr_cli_device.util_ot_ctl, "exec_ot_ctl", return_value="Error: unavailable"):
        assert otbr_cli_device.main(
            ["reset-counters", "2001:db8::1", "--counters", "mac", "--confirm", "--json"]
        ) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["acceptedForTransmission"] is False
    assert result["errorCategory"] == "local-dispatch"


def test_reset_reports_unsupported_tlv_without_claiming_success(capsys) -> None:
    with patch.object(otbr_cli_device.util_ot_ctl, "exec_ot_ctl", return_value="Error: unsupported TLV"):
        assert otbr_cli_device.main(
            ["reset-counters", "2001:db8::1", "--counters", "mle", "--confirm", "--json"]
        ) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["acceptedForTransmission"] is False
    assert result["errorCategory"] == "unsupported"


def test_td_cli_forwards_device_command_to_action_module() -> None:
    parser = td_cli.build_parser()
    args, extras = parser.parse_known_args(["otbr-cli", "device", "ping", "2001:db8::1"])
    with patch.object(td_cli.otbr_cli_device, "main", return_value=0) as action_main:
        assert td_cli.dispatch(args, extras, parser) == 0
    action_main.assert_called_once_with(["ping", "2001:db8::1"])