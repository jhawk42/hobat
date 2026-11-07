from __future__ import annotations

import json
import logging
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from td_logging import format_event, log_event, redact_command_args, redact_sensitive_text


@pytest.mark.parametrize(
    "args,expected",
    [
        (["source-probe", "--json", "--source", "otbr-cli"],
         ["source-probe", "--json", "--source", "otbr-cli"]),
        (["health", "--json", "", "two words", "--json"],
         ["health", "--json", "", "two words", "--json"]),
        (["otbr-cli", "device", "ping", "--json", "--address", "::1"],
         ["otbr-cli", "device", "ping", "--json", "--address", "::1"]),
        (["otbr-restapi", "node", "dataset", "active", "get", "--text", "--raw"],
         ["otbr-restapi", "node", "dataset", "active", "get", "--text", "--raw"]),
        (["otbr-restapi", "node", "dataset", "active", "set", "--json", "SENTINEL"],
         ["otbr-restapi", "node", "dataset", "active", "set", "--json", "[Redacted input]"]),
        (["--json=SENTINEL", "--text", "SENTINEL", "--text=SENTINEL"],
         ["--json=[Redacted input]", "--text", "[Redacted input]", "--text=[Redacted input]"]),
        (["--Access-Token", "SENTINEL", "--odd-secret-shape=SENTINEL", ""],
         ["--Access-Token", "[Redacted input]", "--odd-secret-shape=[Redacted input]", ""]),
        (["otbr-restapi", "--log-thread-secrets", "devices", "list"],
         ["otbr-restapi", "--log-thread-secrets", "devices", "list"]),
        (["source-probe", "--json=SENTINEL", "--source", "otbr-cli"],
         ["source-probe", "--json=[Redacted input]", "--source", "otbr-cli"]),
        (["node", "dataset", "active", "get", "--text=SENTINEL"],
         ["node", "dataset", "active", "get", "--text=[Redacted input]"]),
    ],
)
def test_command_aware_args(args, expected):
    assert redact_command_args(args) == expected


@pytest.mark.parametrize(
    "text",
    [
        '{"NeTwOrK_KeY":"SENTINEL words", "nested":{"PSKC":"SENTINEL"}}',
        'Network Key: "SENTINEL two\\nwords"\nPSKc: SENTINEL',
        "password='SENTINEL with spaces\nand newline'",
        "https://user:SENTINEL@example.test/path?access_token=SENTINEL&name=mesh",
        "custom://SENTINEL@example.test/",
        "accessToken=SENTINEL",
        '{"credentials":["SENTINEL", "SENTINEL two"]}',
        '{"password":{"value":"SENTINEL", "other":"SENTINEL"}}',
        'password="SENTINEL with unclosed quotation',
    ],
)
def test_routine_text_redacts_supported_secrets(text):
    assert "SENTINEL" not in redact_sensitive_text(text)


def test_events_escape_values_and_preserve_identifiers(monkeypatch, caplog, capsys):
    monkeypatch.setenv("TD_RUN_CMD", 'run-1"\nforged=yes')
    monkeypatch.setenv("TD_LOG_THREAD_SECRETS", "1")
    caplog.set_level(logging.INFO)
    log_event(
        "target_progress", source="otbr-restapi", command="diagnostics fetch-all",
        stage="initial", target="0011223344556677",
        detail='two words"\nPSKc: SENTINEL', current=1, total=2, elapsed_s=0.25,
    )
    message = caplog.records[-1].getMessage()
    assert "\n" not in message
    assert "SENTINEL" not in message
    assert "0011223344556677" in message
    assert message.rsplit("elapsed_s=", 1)[1] == "0.250"
    detail = message.split("detail=", 1)[1].split(" current=", 1)[0]
    assert isinstance(json.loads(detail), str)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (0, "0.000"),
        (1, "1.000"),
        (0.25, "0.250"),
        (0.123456789, "0.123"),
        (0.123987654, "0.124"),
        (9.9999, "10.000"),
        (0.00000001, "0.000"),
        (1234567.890123, "1234567.890"),
        (None, "null"),
        (False, "false"),
        ("unavailable", '"unavailable"'),
        (float("inf"), "Infinity"),
        (float("-inf"), "-Infinity"),
        (float("nan"), "NaN"),
    ],
)
def test_event_elapsed_seconds_have_three_decimal_places(elapsed, expected):
    message = format_event(
        "operation_end", source="otbr-cli", command="test", stage="collection",
        elapsed_s=elapsed, duration_s=0.123456789,
        metadata={"elapsed_s": 0.123456789},
    )

    encoded = message.split("elapsed_s=", 1)[1].split(" ", 1)[0]
    assert encoded == expected
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
        assert isinstance(json.loads(encoded), float)
    assert "duration_s=0.123456789 " in message
    assert json.loads(message.split("metadata=", 1)[1]) == {"elapsed_s": 0.123456789}


def test_event_argv_keeps_boundaries(monkeypatch):
    monkeypatch.delenv("TD_RUN_CMD", raising=False)
    args = ["source-probe", "--json", "", "two words", 'quote"\nnewline']
    message = format_event(
        "command_end", source="otbr-cli", command="source-probe", stage="probe",
        argv=redact_command_args(args),
    )
    assert "run_cmd=" not in message
    encoded = message.split("argv=", 1)[1]
    assert json.loads(encoded) == args
    assert "\n" not in message


@pytest.mark.parametrize("outcome", ["success", "timeout", "cancel"])
def test_webserver_existing_log_paths_remain_redacted(monkeypatch, caplog, tmp_path, outcome):
    import td_webserver

    process = MagicMock()
    process.returncode = 0 if outcome == "success" else None
    process.communicate = AsyncMock(return_value=(b"", b""))
    if outcome != "success":
        error = asyncio.TimeoutError() if outcome == "timeout" else asyncio.CancelledError()
        process.communicate.side_effect = [error, (b"", b"")]
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(td_webserver.asyncio, "create_subprocess_exec", create)
    caplog.set_level(logging.DEBUG)
    args = [
        "otbr-restapi", "--log-thread-secrets", "node", "dataset", "active", "set",
        "--json", '{"networkKey":"SENTINEL"}',
    ]

    async def run():
        if outcome == "success":
            assert await td_webserver.run_td_cli(args, tmp_path) == 0
        else:
            with pytest.raises(type(error)):
                await td_webserver.run_td_cli(args, tmp_path, timeout_s=1)

    asyncio.run(run())
    assert "SENTINEL" not in caplog.text
    assert "[Redacted input]" in caplog.text
    assert create.call_args.args[-1] == args[-1]
