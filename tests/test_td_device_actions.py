from __future__ import annotations

import pytest

from td_device_actions import (
    ACTION_MATTER_PING,
    ACTION_OTBR_PING,
    ACTION_OTBR_RESET,
    ACTION_SYSTEM_PING,
    DeviceActionError,
    build_cli_args,
    eligible_record_addresses,
    parse_device_action_request,
    validate_request_against_record,
)


def test_otbr_ping_requires_cached_target_and_sleepy_acknowledgement() -> None:
    record = {
        "extAddress": "aa:bb:cc:dd:ee:ff:00:11",
        "ipv6Addresses": ["fd00::10", "ff03::1"],
        "mode": {"rxOnWhenIdle": False},
    }
    request = parse_device_action_request(
        {
            "action": ACTION_OTBR_PING,
            "deviceId": "extAddress:aabbccddeeff0011",
            "source": "otbr-cli",
            "datasetFiles": ["td-otbr-cli-networkdiag-fetch-all.json"],
            "target": "fd00:0::10",
            "family": "ipv6",
            "attempts": 2,
            "timeoutSeconds": 4,
            "allowSed": True,
        }
    )

    validate_request_against_record(request, record)
    assert build_cli_args(request) == [
        "otbr-cli",
        "device",
        "ping",
        "fd00::10",
        "--count",
        "2",
        "--timeout",
        "4",
        "--json",
        "--allow-sed",
    ]

    unacknowledged = parse_device_action_request(
        {
            "action": ACTION_OTBR_PING,
            "deviceId": "extAddress:aabbccddeeff0011",
            "source": "otbr-cli",
            "datasetFiles": ["td-otbr-cli-networkdiag-fetch-all.json"],
            "target": "fd00::10",
        }
    )
    with pytest.raises(DeviceActionError, match="sleepy"):
        validate_request_against_record(unacknowledged, record)


def test_matter_ping_uses_node_id_without_address_target() -> None:
    record = {"matter": {"nodeId": "4660"}, "networkInterfaces": []}
    request = parse_device_action_request(
        {
            "action": ACTION_MATTER_PING,
            "deviceId": "matterNode:4660",
            "source": "ha-matter-ws",
            "datasetFiles": ["td-ha-matter-ws-dashboard.json"],
            "nodeId": "4660",
            "attempts": 3,
        }
    )

    validate_request_against_record(request, record)
    assert build_cli_args(request) == [
        "ha-matter-ws",
        "device",
        "ping",
        "--node-id",
        "4660",
        "--attempts",
        "3",
    ]


def test_system_ping_normalizes_and_deduplicates_record_addresses() -> None:
    record = {
        "id": "device-1",
        "addresses": ["192.0.2.10", "192.0.2.10"],
        "ipv6Addresses": ["2001:db8:0:0::10", "fe80::10", "ff03::1"],
    }
    assert eligible_record_addresses(record) == [
        {
            "address": "2001:db8::10",
            "family": "ipv6",
            "provenance": "ipv6Addresses",
        },
        {
            "address": "192.0.2.10",
            "family": "ipv4",
            "provenance": "addresses",
        },
    ]

    request = parse_device_action_request(
        {
            "action": ACTION_SYSTEM_PING,
            "deviceId": "id:device-1",
            "source": "mdns",
            "datasetFiles": ["td-mdns-scopes-thread.json"],
            "target": "192.0.2.10",
            "family": "ipv4",
        }
    )
    validate_request_against_record(request, record)
    assert build_cli_args(request)[:7] == [
        "system",
        "device",
        "ping",
        "--address",
        "192.0.2.10",
        "--family",
        "ipv4",
    ]


def test_reset_requires_counter_choice_and_confirmation() -> None:
    with pytest.raises(DeviceActionError, match="confirmation"):
        parse_device_action_request(
            {
                "action": ACTION_OTBR_RESET,
                "deviceId": "rloc16:1234",
                "source": "otbr-cli",
                "datasetFiles": ["td-otbr-cli-networkdiag-fetch-all.json"],
                "target": "fd00::10",
                "counters": "both",
            }
        )


def test_request_rejects_unknown_fields_and_source_mismatch() -> None:
    with pytest.raises(DeviceActionError, match="unsupported request field"):
        parse_device_action_request(
            {
                "action": ACTION_SYSTEM_PING,
                "deviceId": "id:device-1",
                "source": "mdns",
                "datasetFiles": ["td-mdns-scopes-thread.json"],
                "target": "192.0.2.10",
                "arguments": ["--anything"],
            }
        )
    with pytest.raises(DeviceActionError, match="Matter action requires"):
        parse_device_action_request(
            {
                "action": ACTION_MATTER_PING,
                "deviceId": "matterNode:1",
                "source": "mdns",
                "datasetFiles": ["td-mdns-scopes-thread.json"],
                "nodeId": 1,
            }
        )


def test_native_option_bounds_match_cli_contracts() -> None:
    with pytest.raises(DeviceActionError, match="Matter ping attempts"):
        parse_device_action_request(
            {
                "action": ACTION_MATTER_PING,
                "deviceId": "matterNode:1",
                "source": "ha-matter-ws",
                "datasetFiles": ["td-ha-matter-ws-dashboard.json"],
                "nodeId": 1,
                "attempts": 6,
            }
        )
    with pytest.raises(DeviceActionError, match="OTBR timeoutSeconds"):
        parse_device_action_request(
            {
                "action": ACTION_OTBR_PING,
                "deviceId": "rloc16:1234",
                "source": "otbr-cli",
                "datasetFiles": ["td-otbr-cli-networkdiag-fetch-all.json"],
                "target": "fd00::10",
                "timeoutSeconds": 10.5,
            }
        )